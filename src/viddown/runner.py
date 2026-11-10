"""Fronta: kontrola nových URL, spouštění stahování v pořadí přidání, pauzy, plánování, opakování.

Ovládání probíhá přes databázi (GUI/CLI/Telegram zapisují stav, runner na něj reaguje každou sekundu),
takže funguje i když úlohu přidá jiný proces.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import shutil
import time
from pathlib import Path

from . import thumbs
from .config import Settings
from .db import ACTIVE, DB
from .i18n import t
from .probe import probe_url, trim_info
from .resolvers import Cancelled, Ctx, ProcHolder, ResolveError
from .resolvers import sniffer, ytdlp
from .util import (classify_error, fallback_allowed, free_space, in_schedule, render_template, retry_allowed,
                   sanitize_filename, unique_target)

PENDING = ".viddown-pending.json"  # hotové stažení čekající na přesun do cílové složky


def target_available(path: str) -> tuple[bool, str]:
    """Lehká průběžná kontrola cílové složky (bez zkušebního zápisu)."""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"{p}: {e.strerror or e}"
    if not p.is_dir():
        return False, f"{p} není složka"
    if not os.access(p, os.W_OK):
        return False, f"{p}: bez oprávnění k zápisu"
    return True, ""

log = logging.getLogger("viddown.runner")
RETRY_DELAYS = [60, 300, 900]


class Runner:
    def __init__(self, db: DB, settings: Settings, engines, data: Path):
        self.db = db
        self.settings = settings
        self.engines = engines
        self.data = data
        self.running: dict[int, tuple[asyncio.Task, ProcHolder]] = {}
        self.probing: dict[int, asyncio.Task] = {}
        self.stop_reason: dict[int, str] = {}
        self.sibling_gate: dict[int, list[float]] = {}
        self.listeners: list = []
        self._engine_task: asyncio.Task | None = None
        self._disk_warned = False
        self._target_checked = -1e9

    # ------------------------------------------------------------ pomocné
    def ctx(self) -> Ctx:
        return Ctx(self.settings.all(), self.engines, self.data)

    def staging(self, jid: int) -> Path:
        s = self.settings.all()
        base = Path(s["temp_dir"]) if s.get("temp_dir") else self.data / "tmp"
        return base / f"job-{jid}"

    def emit(self, event: str, *args, **kw) -> None:
        for l in self.listeners:
            fn = getattr(l, event, None)
            if fn:
                try:
                    res = fn(*args, **kw)
                    if asyncio.iscoroutine(res):
                        asyncio.ensure_future(res)
                except Exception:  # noqa: BLE001
                    log.exception("listener %s", event)

    def queue_paused(self) -> bool:
        return bool(self.db.kv_get("queue_paused", False))

    def lang(self) -> str:
        return self.settings.get("language", "cs")

    # ------------------------------------------------------------ hlavní smyčka
    async def run(self, stop: asyncio.Event) -> None:
        self.db.recover()
        self._finish_cancelling()
        last_purge = 0.0
        while not stop.is_set():
            try:
                await self.tick()
                if time.time() - last_purge > 3600:
                    last_purge = time.time()
                    self.db.purge_older(int(self.settings.get("history_days", 0)))
            except Exception:  # noqa: BLE001
                log.exception("tick")
            try:
                await asyncio.wait_for(stop.wait(), 1.0)
            except asyncio.TimeoutError:
                pass
        await self.shutdown()

    async def shutdown(self) -> None:
        for jid, (task, holder) in list(self.running.items()):
            self.stop_reason[jid] = "shutdown"
            await holder.stop()
        for task, _ in list(self.running.values()):
            try:
                await asyncio.wait_for(task, 10)
            except Exception:  # noqa: BLE001
                task.cancel()
        # úlohy přerušené ve fázi metadat se vrátí do fronty (jinak to udělá recover při startu)
        self.db.update_where("status='running'", (), status="queued", speed=None, eta=None)
        self._finish_cancelling()

    def _finish_cancelling(self) -> None:
        """Dokončí zrušení úloh, které zůstaly ve stavu 'cancelling', a uklidí osiřelé dočasné složky."""
        for j in self.db.query("select id from jobs where status='cancelling'"):
            shutil.rmtree(self.staging(j["id"]), ignore_errors=True)
            self.db.update(j["id"], status="cancelled", finished_at=time.time(), speed=None, eta=None)
        base = self.staging(0).parent
        if base.exists():
            active = {j["id"] for j in self.db.query("select id from jobs where status in ('queued','running','new','probing','confirm')")}
            for d in base.glob("job-*"):
                try:
                    if int(d.name[4:]) not in active:
                        shutil.rmtree(d, ignore_errors=True)
                except ValueError:
                    pass
        for task in list(self.probing.values()):
            task.cancel()

    async def tick(self) -> None:
        s = self.settings.all()
        now = time.time()

        # 1) kontrola nových URL (vlastní limit, nezabírá sloty stahování)
        free = int(s.get("probe_concurrency", 2)) - len(self.probing)
        if free > 0 and self.db.kv_get("queue_pause_reason") != "cookies":
            for job in self.db.query("select * from jobs where status='new' order by pos limit ?", (free,)):
                self.db.update(job["id"], status="probing")
                self.probing[job["id"]] = asyncio.create_task(self._probe(job))

        # 2) dostupnost cílové složky (např. odpojený NAS) – pozastaví a po obnovení zase pustí frontu
        await self._check_target(s)

        # 3) dohled nad běžícími stahováními
        disk = self.disk_status(s)
        disk_low = disk["low"] is not None
        qpaused = self.queue_paused()
        window = in_schedule(s, now)
        for jid, (task, holder) in list(self.running.items()):
            j = self.db.get(jid)
            reason = None
            if j is None or j["status"] == "cancelling":
                reason = "cancel"
            elif j["paused"]:
                reason = "pause"
            elif qpaused:
                reason = "queue"
            elif not window:
                reason = "schedule"
            elif disk_low:
                reason = "disk"
            if reason and jid not in self.stop_reason:
                self.stop_reason[jid] = reason
                asyncio.create_task(holder.stop())

        if disk_low:
            if not self._disk_warned:
                self._disk_warned = True
                self.db.kv_set("queue_paused", True)
                self.db.kv_set("queue_pause_reason", "disk")
                self.db.kv_set("disk_low", disk["low"])
                self.emit("on_notice", "disk", free=disk["temp_free"] if disk["low"] == "temp" else disk["target_free"])
            return
        self._disk_warned = False

        # 3) automatické aktualizace enginů
        if s.get("engine_auto_update") and (self._engine_task is None or self._engine_task.done()):
            last = float(self.db.kv_get("engine_last_auto", 0) or 0)
            if now - last > float(s.get("engine_update_hours", 24)) * 3600:
                self.db.kv_set("engine_last_auto", now)
                self._engine_task = asyncio.create_task(asyncio.to_thread(self.engines.update_all))

        if qpaused or not window:
            return

        # 4) spuštění dalších úloh v pořadí fronty
        slots = int(s["concurrency"]) - len(self.running)
        if slots <= 0:
            return
        for job in self.db.query(
                "select * from jobs where status='queued' and paused=0 and (not_before is null or not_before<=?) "
                "order by pos limit 50", (now,)):
            if slots <= 0:
                break
            if job["id"] in self.running:
                continue
            pid = job["parent_id"]
            if pid:
                # Pauza mezi videi z playlistu (ochrana proti zablokování) platí pro každý souběžný slot zvlášť:
                # najednou se rozjede až `concurrency` videí a každý slot pak před dalším videem počká 5–15 s.
                gates = [g for g in self.sibling_gate.get(pid, []) if g > now]
                if len(gates) >= int(s["concurrency"]):
                    self.sibling_gate[pid] = gates
                    continue
                gates.append(now + random.uniform(float(s.get("sleep_min", 5)), float(s.get("sleep_max", 15))))
                self.sibling_gate[pid] = gates
            holder = ProcHolder()
            self.db.update(job["id"], status="running", started_at=now, error=None, speed=None, eta=None)
            self.running[job["id"]] = (asyncio.create_task(self._execute(job["id"], holder)), holder)
            slots -= 1

    def disk_status(self, s: dict | None = None) -> dict:
        """Volné místo v dočasné složce (tam vznikají rozpracovaná stahování) a v cílové složce.

        Cílová složka se do kontroly minima počítá jen když je údaj spolehlivý (viz util.free_space)."""
        s = s or self.settings.all()
        temp_dir = self.staging(0).parent
        temp_free, _ = free_space(temp_dir)
        target_free, target_ok = free_space(s["download_dir"])
        same = False
        try:
            same = target_ok and os.stat(temp_dir if temp_dir.exists() else temp_dir.parent).st_dev == os.stat(s["download_dir"]).st_dev
        except OSError:
            pass
        limit = float(s.get("min_free_gb", 2)) * 1024 ** 3
        low = None
        if target_ok and target_free is not None and target_free < limit:
            low = "target"
        elif temp_free is not None and temp_free < limit:
            low = "temp"
        return {"target_free": target_free, "target_reliable": target_ok, "temp_free": temp_free, "temp_dir": str(temp_dir),
                "same_disk": same, "low": low}

    def _pause_for_cookies(self, msg: str) -> None:
        if self.db.kv_get("queue_pause_reason") == "cookies":
            return
        self.db.kv_set("queue_paused", True)
        self.db.kv_set("queue_pause_reason", "cookies")
        self.db.kv_set("cookies_error", msg)
        log.warning("fronta pozastavena – chyba cookies: %s", msg)
        self.emit("on_notice", "cookies", error=msg)

    async def _check_target(self, s: dict) -> None:
        now = time.monotonic()
        if now - self._target_checked < 20:
            return
        self._target_checked = now
        ok, msg = await asyncio.to_thread(target_available, s["download_dir"])
        reason = self.db.kv_get("queue_pause_reason")
        if not ok:
            if not self.queue_paused():
                self.db.kv_set("queue_paused", True)
                self.db.kv_set("queue_pause_reason", "target")
                self.db.kv_set("target_error", msg)
                log.warning("cílová složka není dostupná: %s", msg)
                self.emit("on_notice", "target", error=msg)
        elif self.queue_paused() and reason == "target":
            self.db.kv_set("queue_paused", False)
            self.db.kv_set("queue_pause_reason", None)
            self.db.kv_set("target_error", None)
            log.info("cílová složka je znovu dostupná, fronta pokračuje")

    # ------------------------------------------------------------ kontrola URL
    async def _probe(self, job: dict) -> None:
        jid = job["id"]
        try:
            res = await probe_url(job["url"], self.ctx())
        except Exception as e:  # noqa: BLE001
            log.exception("probe")
            res = {"type": "none", "error": str(e), "error_kind": classify_error(str(e))}
        finally:
            self.probing.pop(jid, None)
        cur = self.db.get(jid)
        if not cur or cur["status"] != "probing":
            return  # mezitím zrušeno
        self.apply_probe(cur, res)

    def needs_confirm(self, job: dict, count: int) -> bool:
        s = self.settings.all()
        if job["auto_confirm"]:
            return False
        if count > int(s.get("playlist_confirm_threshold", 50)):
            return True
        return job["source"] == "telegram" and s.get("telegram_after_probe") == "ask"

    def apply_probe(self, job: dict, res: dict) -> None:
        jid = job["id"]
        s = self.settings.all()
        if res["type"] == "none" and res.get("error_kind") == "cookies":
            self.db.update(jid, status="new", error=res["error"], error_kind="cookies")
            self._pause_for_cookies(res["error"])
            return
        if res["type"] == "none":
            self.db.update(jid, status="failed", error=res["error"], error_kind=res.get("error_kind"),
                           finished_at=time.time(), method=None)
            job = self.db.get(jid)
            self.emit("on_probe", job, res)
            self.emit("on_error", job, res["error"])
            return
        common = dict(title=res.get("title"), thumb_url=res.get("thumb_url"), height=res.get("height"),
                      channel=res.get("channel"), approx=1 if res.get("approx") else 0, method=res.get("method"))
        if res["type"] == "video":
            if res.get("live") and not s.get("live_from_start"):
                self.db.update(jid, status="skipped", error=t(self.lang(), "live_skip"), error_kind="live",
                               finished_at=time.time(), **common)
                self.emit("on_probe", self.db.get(jid), res)
                return
            st = "confirm" if self.needs_confirm(job, 1) else "queued"
            self.db.update(jid, status=st, kind="video", info=res.get("info"), duration=res.get("duration"),
                           size_est=res.get("size_est"), **common)
        else:
            entries = res["entries"]
            st = "confirm" if self.needs_confirm(job, len(entries)) else "expanded"
            self.db.update(jid, status=st, kind=res["type"], info={"entries": entries, "count": len(entries)}, **common)
            if st == "expanded":
                self._expand(self.db.get(jid), entries)
        self.emit("on_probe", self.db.get(jid), res)

    def _expand(self, job: dict, entries: list[dict] | None = None) -> None:
        s = self.settings.all()
        if entries is None:
            entries = (json.loads(job["info"] or "{}")).get("entries") or []
        folder = (job["kind"] == "playlist" and s.get("playlist_folder")) or (job["kind"] == "channel" and s.get("channel_folder"))
        subdir = sanitize_filename(job["title"] or "playlist") if folder else None
        for i, e in enumerate(entries, 1):
            e.setdefault("info", {})
            if e["info"] is not None:
                e["info"]["playlist_index"] = i
        self.db.add_children(job["id"], entries, subdir, job["source"])
        self.db.update(job["id"], status="expanded", info={"count": len(entries)})

    def confirm(self, jid: int) -> bool:
        job = self.db.get(jid)
        if not job or job["status"] != "confirm":
            return False
        if job["kind"] == "video":
            self.db.update(jid, status="queued")
        else:
            self._expand(job)
        return True

    # ------------------------------------------------------------ stahování
    def _rate(self, s: dict) -> int | None:
        if not s.get("rate_limit_enabled"):
            return None
        total = float(s.get("rate_limit_mbps", 10)) * 1024 * 1024
        return int(total / max(1, len(self.running)))

    def _name(self, job: dict, info: dict) -> str:
        s = self.settings.all()
        parent = self.db.get(job["parent_id"]) if job["parent_id"] else None
        tpl = s["channel_name_template"] if parent and parent["kind"] == "channel" else s["name_template"]
        merged = dict(info)
        merged.setdefault("title", job["title"])
        merged.setdefault("channel", job["channel"])
        if parent:
            merged.setdefault("playlist_title", parent["title"])
        return render_template(tpl, merged)

    async def _execute(self, jid: int, holder: ProcHolder) -> None:
        job = self.db.get(jid)
        s = self.settings.all()
        ctx = Ctx(s, self.engines, self.data)
        staging = self.staging(jid)
        info = json.loads(job["info"]) if job["info"] else {}
        methods = list(s.get("methods") or ["ytdlp", "sniffer"])
        if job["method"] == "sniffer" and "sniffer" in methods:
            methods = ["sniffer"]
        errors: list[tuple[str, ResolveError]] = []
        progress_state = {"t": 0.0}

        def on_progress(**kw):
            now = time.monotonic()
            if now - progress_state["t"] < 0.4 and kw.get("progress") != 1.0:
                return
            progress_state["t"] = now
            self.db.update(jid, **kw)

        try:
            result = None
            used = None
            pend = staging / PENDING
            if pend.exists():  # dříve stažené video čeká jen na přesun do cílové složky
                try:
                    d = json.loads(pend.read_text())
                    if Path(d["file"]).exists():
                        result = {"file": Path(d["file"]), "thumb": Path(d["thumb"]) if d.get("thumb") else None,
                                  "log": d.get("log", "")}
                        used = d.get("method")
                        methods = []
                except (OSError, ValueError, KeyError):
                    pass
            for m in methods:
                holder.check()
                try:
                    if m == "ytdlp":
                        result = await self._dl_ytdlp(job, info, ctx, staging, holder, on_progress)
                    elif m == "sniffer":
                        result = await self._dl_sniffer(job, info, ctx, staging, holder, on_progress)
                    used = m
                    break
                except ResolveError as e:
                    errors.append((m, e))
                    log.info("úloha %s metoda %s: %s (%s)", jid, m, e, e.kind)
                    if not fallback_allowed(e.kind):
                        break
                    shutil.rmtree(staging, ignore_errors=True)  # pravidlo: smazat polotovary předchozí metody
            if result is None:
                if not errors:
                    raise ResolveError("žádná metoda neuspěla", "other")
                # rozhoduje chyba hlavní (první) metody, ostatní se jen připíšou
                first_m, first = errors[0]
                msg = str(first) if len(errors) == 1 else " · ".join(
                    f"{'yt-dlp' if m == 'ytdlp' else m}: {e}" for m, e in errors)
                raise ResolveError(msg, first.kind)
            self._finalize(jid, result, used, staging)
        except Cancelled:
            reason = self.stop_reason.pop(jid, "cancel")
            cur = self.db.get(jid)
            if reason == "cancel" or (cur and cur["status"] == "cancelling"):
                shutil.rmtree(staging, ignore_errors=True)
                thumbs.drop(self.data, jid)
                self.db.update(jid, status="cancelled", finished_at=time.time(), speed=None, eta=None)
            else:
                self.db.update(jid, status="queued", speed=None, eta=None)
        except ResolveError as e:
            self.stop_reason.pop(jid, None)
            self._failed(jid, str(e), e.kind, staging)
        except Exception as e:  # noqa: BLE001
            self.stop_reason.pop(jid, None)
            log.exception("úloha %s", jid)
            self._failed(jid, str(e), "other", staging)
        finally:
            self.running.pop(jid, None)
            self._check_parent(jid)

    async def _dl_ytdlp(self, job, info, ctx, staging, holder, on_progress):
        if not info.get("full") or not info.get("requested_formats"):
            fi = await ytdlp.full_info(job["url"], ctx)
            idx = info.get("playlist_index")
            info = trim_info(fi)
            if idx:
                info["playlist_index"] = idx
            self.db.update(job["id"], info=info, title=job["title"] or fi.get("title"), height=ytdlp.best_height(fi),
                           size_est=ytdlp.size_estimate(fi), channel=job["channel"] or fi.get("channel") or fi.get("uploader"),
                           thumb_url=job["thumb_url"] or fi.get("thumbnail"), duration=fi.get("duration"))
            job = self.db.get(job["id"])
        if info.get("is_live") and not ctx.settings.get("live_from_start"):
            return {"skipped": "live"}
        self.db.update(job["id"], method="ytdlp")
        name = self._name(job, info)
        return await ytdlp.download(job["url"], info, ctx, staging, name, self._rate(ctx.settings), on_progress, holder)

    async def _dl_sniffer(self, job, info, ctx, staging, holder, on_progress):
        sn = info.get("sniff")
        if not sn or time.time() - float(info.get("sniffed_at", 0)) > 600:
            sn = await sniffer.sniff(job["url"], ctx)
            if not sn["candidates"]:
                raise ResolveError("video je chráněné DRM" if sn["drm"] else "na stránce nebylo nalezeno žádné video",
                                   "drm" if sn["drm"] else "unsupported")
            self.db.update(job["id"], info={"sniff": sn, "sniffed_at": time.time(), "title": sn["title"]},
                           title=job["title"] or sn["title"], thumb_url=job["thumb_url"] or sn["thumbnail"])
            job = self.db.get(job["id"])
        self.db.update(job["id"], method="sniffer")
        name = self._name(job, {"title": job["title"] or sn.get("title") or "video"})
        return await sniffer.download(sn, ctx, staging, name, on_progress, holder)

    def _finalize(self, jid: int, result: dict, method: str, staging: Path) -> None:
        job = self.db.get(jid)
        if result.get("skipped"):
            msg = {"archive": "Již staženo dříve (archiv)", "live": t(self.lang(), "live_skip")}.get(result["skipped"], result["skipped"])
            self.db.update(jid, status="skipped", error=msg, error_kind=result["skipped"], finished_at=time.time(),
                           speed=None, eta=None, method=method)
            shutil.rmtree(staging, ignore_errors=True)
            return
        s = self.settings.all()
        src: Path = result["file"]
        target_dir = Path(s["download_dir"]) / (job["subdir"] or "")
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = unique_target(target_dir, src.stem, src.suffix)
            shutil.move(str(src), dest)
        except OSError as e:
            # cíl nedostupný (např. odpojený NAS) – hotový soubor zůstane v dočasné složce a přesune se později
            (staging / PENDING).write_text(json.dumps({"file": str(src), "thumb": str(result["thumb"]) if result.get("thumb") else None,
                                                       "method": method, "log": result.get("log") or ""}))
            self._target_checked = -1e9
            raise ResolveError(f"Cílová složka není dostupná ({target_dir}): {e.strerror or e}", "target")
        thumbs.final_jpg(self.data, job, dest, result.get("thumb"), dest.with_suffix(".jpg"),
                         self.engines.get("ffmpeg").bin_path())
        size = dest.stat().st_size
        logf = self.data / "logs"
        logf.mkdir(exist_ok=True)
        (logf / f"job-{jid}.log").write_text(result.get("log") or "", encoding="utf-8")
        self.db.update(jid, status="done", filepath=str(dest), filesize=size, finished_at=time.time(), progress=1.0,
                       downloaded=size, total=size, speed=None, eta=None, method=method, error=None, error_kind=None)
        shutil.rmtree(staging, ignore_errors=True)
        self.emit("on_done", self.db.get(jid))

    def _failed(self, jid: int, msg: str, kind: str, staging: Path) -> None:
        job = self.db.get(jid)
        s = self.settings.all()
        if kind == "cookies":  # chyba nastavení cookies by shodila celou frontu – pozastavit, úloha zůstane
            self.db.update(jid, status="queued", error=msg, error_kind=kind, speed=None, eta=None)
            self._pause_for_cookies(msg)
            return
        if kind == "target":  # počká na dostupnost cílové složky, pokusy se nepočítají
            self.db.update(jid, status="queued", not_before=time.time() + 30, error=msg, error_kind=kind, speed=None, eta=None)
            return
        attempts = (job["attempts"] or 0) + 1
        if retry_allowed(kind) and attempts <= int(s.get("auto_retry_attempts", 2)):
            delay = RETRY_DELAYS[min(attempts - 1, len(RETRY_DELAYS) - 1)]
            self.db.update(jid, status="queued", attempts=attempts, not_before=time.time() + delay,
                           error=msg, error_kind=kind, speed=None, eta=None)
            return
        shutil.rmtree(staging, ignore_errors=True)
        self.db.update(jid, status="failed", attempts=attempts, error=msg, error_kind=kind,
                       finished_at=time.time(), speed=None, eta=None)
        job = self.db.get(jid)
        if not job["parent_id"]:
            self.emit("on_error", job, msg)

    def _check_parent(self, jid: int) -> None:
        job = self.db.get(jid)
        if not job or not job["parent_id"]:
            return
        pid = job["parent_id"]
        kids = self.db.children(pid)
        if any(k["status"] in ACTIVE or k["status"] == "cancelling" for k in kids):
            return
        if self.db.kv_get(f"summary_{pid}"):
            return
        self.db.kv_set(f"summary_{pid}", True)
        failed = [k for k in kids if k["status"] == "failed"]
        parent = self.db.get(pid)
        if failed:
            self.emit("on_summary", parent, failed, len(kids))
        self.emit("on_playlist_done", parent, kids)

    # ------------------------------------------------------------ akce z GUI/CLI/Telegramu
    def add(self, url: str, source: str = "gui", auto_confirm: bool = False, **kw) -> tuple[int, bool]:
        """Přidá URL do fronty. Vrací (id, nová?). Stejná URL ve frontě se nepřidá dvakrát."""
        existing = self.db.find_active_url(url)
        if existing:
            return existing["id"], False
        jid = self.db.add(url, source=source, auto_confirm=1 if auto_confirm else 0, status="new", **kw)
        return jid, True

    def cancel(self, jid: int) -> None:
        job = self.db.get(jid)
        if not job:
            return
        targets = [job] + (self.db.children(jid) if job["kind"] != "video" else [])
        for j in targets:
            if j["status"] == "running":
                self.db.update(j["id"], status="cancelling")
            elif j["status"] in ("new", "probing", "confirm", "queued", "expanded"):
                shutil.rmtree(self.staging(j["id"]), ignore_errors=True)
                self.db.update(j["id"], status="cancelled", finished_at=time.time())
                if j["status"] == "probing" and j["id"] in self.probing:
                    self.probing[j["id"]].cancel()

    def set_paused(self, jid: int, paused: bool) -> None:
        job = self.db.get(jid)
        if not job:
            return
        self.db.update(jid, paused=1 if paused else 0)
        if job["kind"] != "video":
            self.db.update_where("parent_id=? and status in ('queued','running')", (jid,), paused=1 if paused else 0)

    def retry(self, jid: int) -> int | None:
        """Znovu zařadí URL do fronty. U staženého (např. ručně smazaného) nebo přeskočeného videa
        ho nejdřív vyřadí z archivu yt-dlp, jinak by se nové stažení přeskočilo jako „již staženo“."""
        job = self.db.get(jid)
        if not job:
            return None
        if job["status"] in ("done", "skipped"):
            self.archive_forget(job)
        new_id, _ = self.add(job["url"], source=job["source"], auto_confirm=True)
        return new_id

    @staticmethod
    def _archive_key(job: dict) -> tuple[str | None, str]:
        try:
            info = json.loads(job["info"] or "{}")
        except ValueError:
            info = {}
        vid, ext = info.get("id"), (info.get("extractor_key") or "").lower()
        if not vid:
            m = re.search(r"(?:v=|youtu\.be/|/shorts/)([\w-]{11})", job["url"] or "")
            vid, ext = (m.group(1), "youtube") if m else (None, ext)
        return vid, ext

    def archive_forget_many(self, jobs: list[dict]) -> int:
        """Odebere videa z archivu stažených (archive.txt, řádky „extractor id“) jedním přepsáním souboru.
        Vrací počet odebraných řádků."""
        keys = {k for k in (self._archive_key(j) for j in jobs) if k[0]}
        arch = self.data / "archive.txt"
        if not keys or not arch.exists():
            return 0
        lines = arch.read_text(encoding="utf-8").splitlines()

        def hit(line: str) -> bool:
            low, vid = line.lower(), line.split(" ", 1)[-1].strip()
            return any(vid == v and (not e or low.startswith(e + " ")) for v, e in keys)
        keep = [l for l in lines if not hit(l)]
        if len(keep) == len(lines):
            return 0
        tmp = arch.with_suffix(".tmp")
        tmp.write_text("".join(l + "\n" for l in keep), encoding="utf-8")
        os.replace(tmp, arch)
        log.info("z archivu vyřazeno %d videí (stáhnou se znovu)", len(lines) - len(keep))
        return len(lines) - len(keep)

    def archive_forget(self, job: dict) -> bool:
        """Odebere jedno video z archivu stažených."""
        return self.archive_forget_many([job]) > 0
