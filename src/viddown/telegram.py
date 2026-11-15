"""Telegram bot (long polling – nepotřebuje veřejnou adresu).

Reaguje jen na povolené chat ID. Po URL odpoví počtem nalezených videí a rozlišením prvního,
podle nastavení stáhne hned nebo se zeptá tlačítky. Dál hlásí jen chyby (u playlistu souhrnně).
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .i18n import t
from .util import extract_urls, fmt_bytes

log = logging.getLogger("viddown.telegram")
API = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    def __init__(self, runner, db, settings, secrets, engines):
        self.runner, self.db, self.settings, self.secrets, self.engines = runner, db, settings, secrets, engines
        self.state = "off"
        self.username = None
        self.error = None
        self._reload = asyncio.Event()
        self._client: httpx.AsyncClient | None = None
        self._token = None
        self.loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ stav
    def status(self) -> dict:
        return {"state": self.state, "username": self.username, "error": self.error}

    def reload(self) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(self._reload.set)
        else:
            self._reload.set()

    def lang(self) -> str:
        return self.settings.get("language", "cs")

    def chat(self) -> str:
        return str(self.settings.get("telegram_chat_id") or "").strip()

    def sender_ok(self, chat: dict, sender: dict | None) -> bool:
        """Osobní chat stačí ověřit podle ID chatu. Ve skupině by bota jinak ovládal každý člen, proto smí jen uživatelé uvedení
        v nastavení `telegram_user_ids`; bez něj se skupina ignoruje."""
        if (chat or {}).get("type", "private") == "private":
            return True
        ids = {x.strip() for x in str(self.settings.get("telegram_user_ids") or "").split(",") if x.strip()}
        return bool(sender and str(sender.get("id")) in ids)

    # ------------------------------------------------------------ API
    async def call(self, method: str, http_timeout: float = 30, **params):
        if not self._client or not self._token:
            raise RuntimeError("bot není připojen")
        r = await self._client.post(API.format(token=self._token, method=method), json=params, timeout=http_timeout)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"HTTP {r.status_code}")
        return data["result"]

    async def send(self, text: str, chat: str | None = None, **kw):
        chat = chat or self.chat()
        if not chat or self.state not in ("ok",):
            return None
        try:
            return await self.call("sendMessage", chat_id=chat, text=text[:4000], disable_web_page_preview=True, **kw)
        except Exception as e:  # noqa: BLE001
            log.warning("sendMessage: %s", e)
            return None

    async def edit(self, chat, msg_id, text, keyboard=None):
        try:
            params = dict(chat_id=chat, message_id=int(msg_id), text=text[:4000], disable_web_page_preview=True)
            params["reply_markup"] = {"inline_keyboard": keyboard} if keyboard else {"inline_keyboard": []}
            await self.call("editMessageText", **params)
        except Exception as e:  # noqa: BLE001
            if "not modified" not in str(e):
                log.warning("editMessageText: %s", e)

    async def send_test(self):
        if self.state != "ok":
            return False, {"off": "Bot není zapnutý (chybí token)", "nochat": "Chybí povolené chat ID", "error": self.error or "chyba"}.get(self.state, self.state)
        r = await self.send("✅ VidDown: testovací zpráva")
        return (True, "") if r else (False, "Zprávu se nepodařilo odeslat")

    def notify_threadsafe(self, key: str, **kw) -> None:
        """Pro volání z jiných vláken (aktualizace enginů)."""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.send(t(self.lang(), key, **kw)), self.loop)

    # ------------------------------------------------------------ smyčka
    async def run(self, stop: asyncio.Event) -> None:
        self.loop = asyncio.get_running_loop()
        async with httpx.AsyncClient() as client:
            self._client = client
            while not stop.is_set():
                self._reload.clear()
                self._token = self.secrets.telegram_token
                if not self._token:
                    self.state, self.username = "off", None
                    await self._wait(stop, 3600)
                    continue
                try:
                    me = await self.call("getMe")
                    self.username = me.get("username")
                    self.error = None
                    self.state = "ok" if self.chat() else "nochat"
                    log.info("Telegram bot @%s připojen", self.username)
                    await self.call("setMyCommands", commands=[
                        {"command": "fronta", "description": "Fronta / queue"},
                        {"command": "historie", "description": "Historie / history"},
                        {"command": "engine", "description": "Verze enginů / engine versions"},
                        {"command": "aktualizovat", "description": "Aktualizovat enginy / update engines"},
                        {"command": "aplikace", "description": "Verze aplikace a její aktualizace / app version and updates"},
                        {"command": "pomoc", "description": "Nápověda / help"}])
                    offset = None
                    while not stop.is_set() and not self._reload.is_set():
                        self.state = "ok" if self.chat() else "nochat"
                        params = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
                        if offset is not None:
                            params["offset"] = offset
                        poll = asyncio.create_task(self.call("getUpdates", http_timeout=40, **params))
                        waiter = asyncio.create_task(self._reload.wait())
                        stopper = asyncio.create_task(stop.wait())
                        done, _ = await asyncio.wait({poll, waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
                        for tsk in (waiter, stopper):
                            tsk.cancel()
                        if poll not in done:
                            poll.cancel()
                            break
                        for u in poll.result():
                            offset = u["update_id"] + 1
                            try:
                                await self.handle(u)
                            except Exception:  # noqa: BLE001
                                log.exception("update")
                except Exception as e:  # noqa: BLE001
                    self.state, self.error = "error", str(e)
                    log.warning("Telegram: %s", e)
                    await self._wait(stop, 15)
        self._client = None

    async def _wait(self, stop, sec):
        w1, w2 = asyncio.create_task(self._reload.wait()), asyncio.create_task(stop.wait())
        await asyncio.wait({w1, w2}, timeout=sec, return_when=asyncio.FIRST_COMPLETED)
        w1.cancel()
        w2.cancel()

    # ------------------------------------------------------------ zprávy
    async def handle(self, u: dict) -> None:
        L = self.lang()
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = str(cq["message"]["chat"]["id"])
            if chat != self.chat() or not self.sender_ok(cq["message"]["chat"], cq.get("from")):
                return
            action, _, jid = (cq.get("data") or "").partition(":")
            if action == "app":
                if cq["message"]["chat"].get("type") != "private":         # aktualizace a restart jen z osobního chatu (ve skupině by je mohl spustit kdokoli)
                    await self.call("answerCallbackQuery", callback_query_id=cq["id"], text="—", show_alert=True)
                    return
                await self.call("answerCallbackQuery", callback_query_id=cq["id"])
                await self._app_action(jid)
                return
            jid = int(jid or 0)
            if action == "ok":
                ok = self.runner.confirm(jid)
                await self.call("answerCallbackQuery", callback_query_id=cq["id"], text=t(L, "queued") if ok else "—")
                if ok:
                    job = self.db.get(jid)
                    await self.edit(chat, cq["message"]["message_id"], (cq["message"].get("text") or "").split("\n")[0] + "\n" + t(L, "queued"))
            elif action == "no":
                self.runner.cancel(jid)
                await self.call("answerCallbackQuery", callback_query_id=cq["id"], text=t(L, "cancelled"))
                await self.edit(chat, cq["message"]["message_id"], (cq["message"].get("text") or "").split("\n")[0] + "\n" + t(L, "cancelled"))
            return
        msg = u.get("message")
        if not msg:
            return
        chat = str(msg["chat"]["id"])
        if chat != self.chat():
            if msg["chat"].get("type") == "private":
                await self.call("sendMessage", chat_id=chat, text=t(L, "not_allowed", id=chat))
            return
        if not self.sender_ok(msg["chat"], msg.get("from")):                 # skupina: jen povolení uživatelé
            return
        text = msg.get("text") or msg.get("caption") or ""
        cmd = text.strip().split()[0].lower().split("@")[0] if text.strip().startswith("/") else ""
        if cmd in ("/start", "/help", "/pomoc"):
            await self.send(t(L, "help"))
            return
        if cmd in ("/fronta", "/queue"):
            await self.send(self._queue_text())
            return
        if cmd in ("/historie", "/history"):
            await self.send(self._history_text())
            return
        if cmd == "/engine":
            await self.send(self._engine_text())
            return
        if cmd in ("/aplikace", "/app"):
            await self._app_status()
            return
        if cmd in ("/aktualizovat", "/update"):
            await self.send(t(L, "updating"))
            res = await asyncio.to_thread(self.engines.update_all)
            await self.send("\n".join(f"{n}: {r.get('status')} {r.get('version') or ''}" for n, r in res.items()))
            return
        urls = extract_urls(text)
        for ent in msg.get("entities") or []:
            if ent.get("type") == "text_link" and ent.get("url") not in urls and str(ent.get("url") or "").lower().startswith(("http://", "https://")):
                urls.append(ent["url"])
        if not urls:
            await self.send(t(L, "no_url"))
            return
        for url in urls:
            m = await self.call("sendMessage", chat_id=chat, text=f"{url}\n{t(L, 'probing')}",
                                reply_to_message_id=msg["message_id"], disable_web_page_preview=True)
            jid, new = self.runner.add(url, source="telegram", tg_chat=chat, tg_msg=str(m["message_id"]))
            if not new:
                await self.edit(chat, m["message_id"], f"{url}\n{t(L, 'already')}")

    # ------------------------------------------------------------ aktualizace aplikace
    async def _app_status(self, check: bool = True) -> None:
        from . import updater
        L, st = self.lang(), getattr(self, "app", None)
        if st is None:
            return
        try:
            if check:
                await asyncio.to_thread(updater.do_check, st)
        except Exception as e:  # noqa: BLE001
            await self.send(f"⚠️ {e}")
        s = await asyncio.to_thread(updater.status, st)
        chk = s.get("check") or {}
        label = {"available": f"🆕 {chk.get('version')}", "up_to_date": "✅", "skipped": "⏭", "needs_image": "🐳", "error": f"⚠️ {chk.get('error', '')}"}.get(chk.get("status"), "—")
        kb = []
        if s["prepared"] and not s["applying"]:
            kb = [[{"text": t(L, "app_btn_apply"), "callback_data": "app:apply"}], [{"text": t(L, "app_btn_restart"), "callback_data": "app:restart"}]]
        elif chk.get("status") == "available":
            kb = [[{"text": t(L, "app_btn_update"), "callback_data": "app:update"}]]
        await self.send(t(L, "app_status", running=s["running"], baseline=s["baseline"], current=s["current"] or t(L, "app_none"), check=label),
                        **({"reply_markup": {"inline_keyboard": kb}} if kb else {}))

    async def _app_action(self, what: str) -> None:
        from . import appupdate, updater
        L, st = self.lang(), getattr(self, "app", None)
        if st is None:
            return
        try:
            if what == "update":
                await self.send(t(L, "app_updating"))
                r = await asyncio.to_thread(updater.do_update, st)
                await self.send(f"✅ {r['result'].get('version', '')}")
                await self._app_status(check=False)
            elif what == "apply":
                await self.send(t(L, "app_apply_started"))
                updater.spawn_apply(st)
            elif what == "restart":
                await self.send(t(L, "app_restarting"))
                updater.request_restart(st)
        except appupdate.UpdateError as e:
            await self.send(f"⚠️ {e}")

    def _queue_text(self) -> str:
        L = self.lang()
        q = [j for j in self.db.queue() if j["kind"] == "video" or j["status"] in ("confirm", "new", "probing")]
        if not q:
            return t(L, "queue_empty")
        st = t(L, "status")
        lines = [t(L, "queue_head", n=len(q))]
        for j in q[:20]:
            p = f" {int((j['progress'] or 0) * 100)} %" if j["status"] == "running" else ""
            lines.append(f"• {(j['title'] or j['url'])[:60]} – {st.get(j['status'], j['status'])}{p}{' ⏸' if j['paused'] else ''}")
        if len(q) > 20:
            lines.append(f"… +{len(q) - 20}")
        return "\n".join(lines)

    def _history_text(self) -> str:
        L = self.lang()
        h = self.db.history(limit=10)
        if not h:
            return t(L, "history_empty")
        st = t(L, "status")
        return "\n".join(f"• {(j['title'] or j['url'])[:60]} – {st.get(j['status'], j['status'])}"
                         f"{' · ' + fmt_bytes(j['filesize']) if j['filesize'] else ''}" for j in h)

    def _engine_text(self) -> str:
        out = []
        for e in self.engines.status():
            out.append(f"{e['name']}: {e['current'] or (str(e['system']) + ' (systém)' if e['system'] else '—')}")
        return "\n".join(out)

    # ------------------------------------------------------------ události z fronty
    async def on_probe(self, job: dict, res: dict) -> None:
        if job.get("source") != "telegram" or not job.get("tg_msg") or self.state != "ok":
            return
        L = self.lang()
        head = job["url"] if not job.get("title") else job["title"]
        if res["type"] == "none":
            kind = res.get("error_kind")
            body = t(L, "drm") if kind == "drm" else t(L, "not_found") if kind == "unsupported" else t(L, "failed_probe", err=res.get("error", ""))
            await self.edit(job["tg_chat"], job["tg_msg"], f"{job['url']}\n{body}")
            return
        if job["status"] == "skipped":
            await self.edit(job["tg_chat"], job["tg_msg"], f"{head}\n{job.get('error') or ''}")
            return
        res_txt = f"{res['height']}p" if res.get("height") else "?"
        approx = t(L, "approx") if res.get("approx") else ""
        if res["type"] == "video":
            body = t(L, "found_video", res=res_txt, approx=approx)
        else:
            body = t(L, "found_many", n=res["count"], res=res_txt, approx=approx)
        if job["status"] == "confirm":
            limit = int(self.settings.get("playlist_confirm_threshold", 50))
            ask = t(L, "ask_big", n=res["count"], limit=limit) if res.get("count", 1) > limit else t(L, "ask")
            kb = [[{"text": t(L, "btn_download"), "callback_data": f"ok:{job['id']}"},
                   {"text": t(L, "btn_cancel"), "callback_data": f"no:{job['id']}"}]]
            await self.edit(job["tg_chat"], job["tg_msg"], f"{head}\n{body}\n{ask}", kb)
        else:
            await self.edit(job["tg_chat"], job["tg_msg"], f"{head}\n{body}\n{t(L, 'queued')}")

    async def on_error(self, job: dict, msg: str) -> None:
        if job.get("source") != "telegram":
            return  # chyby videí přidaných jinak (GUI, katalog, odběr, CLI) se do Telegramu neposílají, jsou v GUI
        if job.get("source") == "telegram" and job.get("status") == "failed" and not job.get("method") and job.get("tg_msg"):
            return  # chyba kontroly už je v upravené odpovědi na URL
        await self.send(t(self.lang(), "err_job", title=job.get("title") or job["url"], err=msg))

    async def on_summary(self, parent: dict, failed: list[dict], total: int) -> None:
        if parent.get("source") != "telegram":
            return  # souhrn selhání playlistu jen u playlistů zadaných přes Telegram
        lines = "\n".join(f"• {(f['title'] or f['url'])[:60]}: {(f['error'] or '')[:120]}" for f in failed[:10])
        if len(failed) > 10:
            lines += f"\n… +{len(failed) - 10}"
        await self.send(t(self.lang(), "err_summary", title=parent.get("title") or parent["url"], failed=len(failed), total=total, lines=lines))

    async def on_done(self, job: dict) -> None:
        if self.settings.get("telegram_notify") == "all":
            await self.send(t(self.lang(), "done_job", title=job.get("title") or job["url"], path=job.get("filepath") or ""))

    async def on_notice(self, kind: str, **kw) -> None:
        if kind == "cookies":
            await self.send(("⚠️ Fronta pozastavena: cookies nejdou načíst ({e}). Opravte nastavení cookies a frontu obnovte v GUI."
                             if self.lang() == "cs" else "⚠️ Queue paused: cookies can't be loaded ({e}). Fix the cookie settings and resume the queue in the GUI.")
                            .format(e=kw.get("error", "")[:200]))
            return
        if kind == "yt_cookies":
            await self.send("⚠️ YouTube přestal uznávat nahrané cookies. Věkově omezená videa se nestáhnou, dokud je neobnovíte (Nastavení › cookies.txt)."
                            if self.lang() == "cs" else
                            "⚠️ YouTube no longer accepts the uploaded cookies. Age-restricted videos will fail until you refresh them (Settings › cookies.txt).")
            return
        if kind == "target":
            await self.send(("⚠️ Fronta pozastavena: cílová složka není dostupná ({e}). Po obnovení přístupu bude pokračovat."
                             if self.lang() == "cs" else "⚠️ Queue paused: download folder unavailable ({e}). It resumes when the folder is back.")
                            .format(e=kw.get("error", "")))
            return
        if kind == "disk":
            await self.send(("⚠️ Fronta pozastavena: málo místa na disku ({free})." if self.lang() == "cs"
                             else "⚠️ Queue paused: low disk space ({free}).").format(free=fmt_bytes(kw.get("free"))))
