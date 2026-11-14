"""Fronta: kontrola nových URL, spouštění stahování v pořadí přidání, pauzy, plánování, opakování.

Ovládání probíhá přes databázi (GUI/CLI/Telegram zapisují stav, runner na něj reaguje každou sekundu),
takže funguje i když úlohu přidá jiný proces.
"""
from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import random
import re
import shutil
import time
from pathlib import Path

from . import cpu, schedule, subscriptions, thumbs
from .config import Settings
from .db import ACTIVE, DB
from .i18n import t
from .probe import probe_url, trim_info
from .resolvers import Cancelled, Ctx, ProcHolder, ResolveError
from .resolvers import pages, sniffer, ytdlp
from .util import (classify_error, fallback_allowed, free_space, in_schedule, render_template, retry_allowed,
                   sanitize_filename, unique_target)

PENDING = ytdlp.PENDING  # hotové stažení čekající na přesun do cílové složky


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
DISK_TIMEOUT = 8.0          # nejdéle tak dlouho čeká tick na zjištění volného místa (zaseknutý síťový disk)


class Runner:
    def __init__(self, db: DB, settings: Settings, engines, data: Path):
        self.db = db
        self.settings = settings
        self.engines = engines
        self.data = data
        self.cpu = cpu.Monitor()
        self.phases: dict[int, dict] = {}
        self._prev_task: asyncio.Task | None = None
        self._prev_next = 0.0
        self._temp_cache: tuple[float, int] = (-1e9, 0)
        self._disk_cache: tuple[float, dict | None] = (-1e9, None)
        self._disk_task: asyncio.Future | None = None
        self.running: dict[int, tuple[asyncio.Task, ProcHolder]] = {}
        self.probing: dict[int, asyncio.Task] = {}
        self.stop_reason: dict[int, str] = {}
        self.sibling_gate: dict[int, list[float]] = {}
        self.listeners: list = []
        self._engine_task: asyncio.Task | None = None
        self._sub_task: asyncio.Task | None = None
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

    def pause_is_hard(self) -> bool:
        """Pozastavená fronta přeruší i běžící úlohy, pokud jde o „Pozastavit vše“ nebo o jiný důvod než ruční pozastavení
        (cookies, nedostupná cílová složka, málo místa). Ruční „Pozastavit frontu“ nechá rozpracované doběhnout."""
        if not self.queue_paused():
            return False
        return bool(self.db.kv_get("queue_pause_hard", False)) or self.db.kv_get("queue_pause_reason") != "user"

    def queue_paused(self) -> bool:
        return bool(self.db.kv_get("queue_paused", False))

    def lang(self) -> str:
        return self.settings.get("language", "cs")

    # ------------------------------------------------------------ hlavní smyčka
    def eff_concurrency(self, s: dict) -> int:
        """Souběžná stahování po zohlednění režimu výkonu (Šetrný = nejvýše 1)."""
        n = int(s["concurrency"])
        cap = cpu.MODES.get(s.get("perf_mode", "full"), cpu.MODES["full"])[2]
        return min(n, cap) if cap else n

    async def run(self, stop: asyncio.Event) -> None:
        self.db.recover()
        self._finish_cancelling()
        last_purge = 0.0
        while not stop.is_set():
            try:
                self.cpu.sample(str(self.settings.get("perf_mode", "full")))
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
        disk = await self.disk_status_async(s)
        disk_low = disk["low"] is not None
        qpaused = self.queue_paused()
        hard = self.pause_is_hard()
        window = schedule.allowed(s, "queue", now, self.db)
        for jid, (task, holder) in list(self.running.items()):
            j = self.db.get(jid)
            reason = None
            if j is None or j["status"] == "cancelling":
                reason = "cancel"
            elif j["paused"]:
                reason = "pause"
            elif qpaused and hard:
                reason = "queue"
            elif not window and not s.get("schedule_finish_running"):      # okno skončilo: rozpracované se přeruší (nebo doběhnou)
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

        # 3b) odběry: kontrola nových videí (po jednom odběru, jen když fronta není pozastavená)
        hours = float(s.get("subscription_check_hours") or 0)
        if not qpaused and (self._sub_task is None or self._sub_task.done()) and schedule.allowed(s, "subscriptions", now, self.db):
            sub = subscriptions.due(self.db, hours, now)
            if sub:
                self._sub_task = asyncio.create_task(self._check_sub(sub["id"]))

        # 3c) náhledy a názvy čekajících položek (po jedné s odstupem, ať to nezatěžuje web ani procesor)
        if s.get("queue_previews", True) and (self._prev_task is None or self._prev_task.done()) and time.monotonic() >= self._prev_next \
                and self.cpu.mode != "eco" and window:
            job = self.db.query(
                "select * from jobs where kind='video' and status='queued' and thumb_url is null and method is null "
                "and coalesce(info,'') not like '%\"preview_tried\"%' order by pos limit 1")
            if job:
                self._prev_task = asyncio.create_task(self._preview(job[0]))

        if qpaused or not window:
            return

        # 4) spuštění dalších úloh v pořadí fronty
        slots = self.eff_concurrency(s) - len(self.running)
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
                if len(gates) >= self.eff_concurrency(s):
                    self.sibling_gate[pid] = gates
                    continue
                gates.append(now + random.uniform(float(s.get("sleep_min", 5)), float(s.get("sleep_max", 15))))
                self.sibling_gate[pid] = gates
            holder = ProcHolder()
            self.db.update(job["id"], status="running", started_at=now, error=None, speed=None, eta=None)
            self.running[job["id"]] = (asyncio.create_task(self._execute(job["id"], holder)), holder)
            slots -= 1

    def temp_usage(self) -> int:
        """Velikost rozpracovaných stahování v dočasné složce (počítá se nejvýše jednou za 30 s – na síťovém disku je to pomalé)."""
        now = time.monotonic()
        if now - self._temp_cache[0] < 30:
            return self._temp_cache[1]
        total = 0
        base = self.staging(0).parent
        try:
            for d in base.glob("job-*"):
                for root, _dirs, files in os.walk(d):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
        except OSError:
            pass
        self._temp_cache = (now, total)
        return total

    def disk_cached(self, s: dict | None = None) -> dict:
        """Naposledy zjištěný stav disků (obnovuje ho `tick`); pro GUI, aby dotaz na stav nezávisel na zaseknutém síťovém disku."""
        return self._disk_cache[1] if self._disk_cache[1] is not None else self.disk_status(s)

    async def disk_status_async(self, s: dict | None = None) -> dict:
        """`disk_status` ve vlákně s časovým limitem: zaseknutý NFS/SMB disk nezastaví celou aplikaci (použije se poslední známý stav).
        Dokud předchozí dotaz neskončí, nový se nespouští."""
        now = time.monotonic()
        task = self._disk_task
        if task is None or task.done():
            if now - self._disk_cache[0] >= 1.0 or self._disk_cache[1] is None:
                self._disk_task = task = asyncio.ensure_future(asyncio.to_thread(self.disk_status, s))
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), DISK_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning("zjištění volného místa trvá příliš dlouho (zaseknutý disk?)")
        if task is not None and task.done() and not task.cancelled() and task.exception() is None:
            self._disk_cache = (time.monotonic(), task.result())
        if self._disk_cache[1] is None:
            return {"target_free": None, "target_reliable": False, "temp_free": None, "temp_dir": str(self.staging(0).parent),
                    "same_disk": False, "low": None, "temp_used": 0}
        return self._disk_cache[1]

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
                "same_disk": same, "low": low, "temp_used": self.temp_usage()}

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
        if res.get("resolved_url") and res["resolved_url"] != cur["url"]:
            # story odkazovala na jiné video: stahuje se jeho adresa, původní URL zůstává v info (origin_url)
            self.db.update(jid, url=res["resolved_url"])
            cur = self.db.get(jid)
        self.apply_probe(cur, res)

    async def _preview(self, job: dict) -> None:
        """Doplní čekající položce název, náhled, délku a odhad velikosti (a uloží plné info, takže ho stažení nemusí
        zjišťovat znovu). Při chybě se položka označí, aby se nezkoušela pořád dokola."""
        jid = job["id"]
        try:
            fi = await ytdlp.full_info(job["url"], self.ctx(), timeout=90)
            cur = self.db.get(jid)
            if not cur or cur["status"] != "queued":
                return
            old = json.loads(cur["info"]) if cur["info"] else {}
            info = trim_info(fi)
            if old.get("playlist_index"):
                info["playlist_index"] = old["playlist_index"]
            self.db.update(jid, info=info, title=cur["title"] if cur["title"] and not str(cur["title"]).startswith("http") else fi.get("title"),
                           height=ytdlp.best_height(fi), size_est=ytdlp.size_estimate(fi),
                           channel=cur["channel"] or fi.get("channel") or fi.get("uploader"),
                           thumb_url=cur["thumb_url"] or fi.get("thumbnail"), duration=cur["duration"] or fi.get("duration"))
        except Exception as e:  # noqa: BLE001
            log.debug("náhled položky %s: %s", jid, e)
            cur = self.db.get(jid)
            if cur and cur["status"] == "queued":
                old = json.loads(cur["info"]) if cur["info"] else {}
                old["preview_tried"] = True
                self.db.update(jid, info=old)
        finally:
            self._prev_next = time.monotonic() + random.uniform(2.0, 4.0)

    # ------------------------------------------------------------ odběry
    async def _check_sub(self, sid: int) -> dict:
        try:
            return await subscriptions.check(self, sid)
        except Exception as e:  # noqa: BLE001
            log.exception("odběr %s", sid)
            self.db.sub_update(sid, last_check=time.time(), last_error=str(e))
            return {"error": str(e)}

    def check_subscription_now(self, sid: int) -> bool:
        """Spustí kontrolu odběru hned. False, když se právě kontroluje (jiný) odběr."""
        if self._sub_task is not None and not self._sub_task.done():
            return False
        if not self.db.sub_get(sid):
            return False
        self._sub_task = asyncio.create_task(self._check_sub(sid))
        return True

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
            confirm = self.needs_confirm(job, len(entries))
            # „rozbalený“ se z playlistu stane až v `_expand`, po vložení videí (výjimka nebo pád mezi tím by nechal rodiče bez dětí)
            self.db.update(jid, status="confirm" if confirm else "probing", kind=res["type"], info={"entries": entries, "count": len(entries)}, **common)
            if not confirm:
                try:
                    self._expand(self.db.get(jid), entries)
                except Exception as e:  # noqa: BLE001
                    log.exception("rozbalení playlistu %s", jid)
                    self.db.update(jid, status="failed", error=f"Playlist se nepodařilo rozbalit: {e}", error_kind="other", finished_at=time.time())
                    self.emit("on_error", self.db.get(jid), str(e))
                    return
        self.emit("on_probe", self.db.get(jid), res)

    def _expand(self, job: dict, entries: list[dict] | None = None) -> None:
        s = self.settings.all()
        if entries is None:
            entries = (json.loads(job["info"] or "{}")).get("entries") or []
        folder = (job["kind"] == "playlist" and s.get("playlist_folder")) or (job["kind"] == "channel" and s.get("channel_folder"))
        subdir = sanitize_filename(job["title"] or "playlist") if folder else None
        # videa, která už jsou ve frontě (z jiného playlistu nebo zadaná zvlášť), se nepřidávají podruhé
        seen: set[str] = set()
        kept = []
        for e in entries:
            u = e.get("url")
            if u and (u in seen or self.db.find_active_url(u)):
                continue
            seen.add(u)
            kept.append(e)
        if len(kept) != len(entries):
            log.info("playlist %s: %d videí už je ve frontě, přeskočeno", job["id"], len(entries) - len(kept))
        total = len(entries)
        entries = kept
        for e in entries:                                           # seznam playlistů: každý playlist do podsložky podle svého názvu
            if e.get("group"):
                e["subdir"] = "/".join(p for p in (subdir, sanitize_filename(e["group"])) if p)
        for i, e in enumerate(entries, 1):
            e.setdefault("info", {})
            if e["info"] is not None:
                e["info"]["playlist_index"] = i
        if not entries:                                              # všechna videa už jsou ve frontě: není co čekat ani shrnovat
            self.db.update(job["id"], status="skipped", error="Všechna videa playlistu už jsou ve frontě", error_kind="duplicate",
                           finished_at=time.time(), info={"count": 0, "duplicates": total})
            return
        self.db.add_children(job["id"], entries, subdir, job["source"])
        self.db.update(job["id"], status="expanded", info={"count": len(entries), "duplicates": total - len(entries)})

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
        sub = self.db.sub_get(job["sub_id"]) if job.get("sub_id") else None
        is_channel = (parent and parent["kind"] == "channel") or (sub and sub["kind"] == "channel")
        tpl = s["channel_name_template"] if is_channel else s["name_template"]
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
        ph = self.phases[jid] = {"t0": time.monotonic()}
        self.db.update(jid, stage="download")

        def on_progress(**kw):
            if kw.pop("phase", None) == "post" and "post" not in ph:
                ph["post"] = time.monotonic()
                self.db.update(jid, stage="post")
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
            ph["end"] = time.monotonic()
            self.db.update(jid, stage="move")
            await self._finalize_async(jid, result, used, staging)
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
            self.phases.pop(jid, None)
            self.db.update(jid, stage=None)
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
            if pages.is_story_url(job["url"]):
                st = await pages.open_story(job["url"], ctx)
                if "sniff" not in st:
                    raise ResolveError("story už neobsahuje vlastní video", "unsupported")
                sn = st["sniff"]
            else:
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

    def _skip_result(self, jid: int, result: dict, method: str, staging: Path) -> bool:
        if not result.get("skipped"):
            return False
        msg = {"archive": "Již staženo dříve (archiv)", "live": t(self.lang(), "live_skip")}.get(result["skipped"], result["skipped"])
        self.db.update(jid, status="skipped", error=msg, error_kind=result["skipped"], finished_at=time.time(),
                       speed=None, eta=None, method=method)
        shutil.rmtree(staging, ignore_errors=True)
        return True

    def _place(self, jid: int, result: dict, method: str, staging: Path) -> Path:
        """Vstupně-výstupní část dokončení (běží ve vlákně, ať velký přesun na NAS nezastaví aplikaci): přesune soubor do cíle pod
        dočasným názvem a teprve hotový ho přejmenuje, takže po výpadku uprostřed kopie nezůstane v cíli poloviční video."""
        job = self.db.get(jid)
        s = self.settings.all()
        src: Path = result["file"]
        # úloha z odběru má vlastní cílovou složku, ostatní ukládá do download_dir (případně do podsložky playlistu)
        target_dir = Path(job["target_dir"]) if job.get("target_dir") else Path(s["download_dir"]) / (job["subdir"] or "")
        part = None
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = unique_target(target_dir, src.stem, src.suffix)
            part = dest.with_name(dest.name + ".viddown-part")
            part.unlink(missing_ok=True)
            shutil.move(str(src), part)
            os.replace(part, dest)
            part = None
        except OSError as e:
            if part is not None:
                try:
                    part.unlink(missing_ok=True)                       # poloviční kopie se v cíli nenechává
                except OSError:
                    pass
            # cíl nedostupný (např. odpojený NAS) – hotový soubor zůstane v dočasné složce a přesune se později
            ytdlp.save_pending(staging, src if src.exists() else Path(str(part or src)), result.get("thumb"), result.get("log") or "", method)
            self._target_checked = -1e9
            if e.errno in (errno.ENOSPC, errno.EDQUOT):
                self.db.kv_set("queue_paused", True)
                self.db.kv_set("queue_pause_reason", "disk")
                raise ResolveError(f"V cílové složce není místo ({target_dir}): {e.strerror or e}", "disk")
            raise ResolveError(f"Cílová složka není dostupná ({target_dir}): {e.strerror or e}", "target")
        try:
            thumbs.final_jpg(self.data, job, dest, result.get("thumb"), dest.with_suffix(".jpg"), self.engines.get("ffmpeg").bin_path())
        except Exception as e:  # noqa: BLE001 - chybějící miniatura nesmí shodit úlohu, když je video už v cíli
            log.warning("miniaturu k %s se nepodařilo vytvořit: %s", dest.name, e)
        return dest

    def _complete(self, jid: int, dest: Path, result: dict, method: str, staging: Path) -> None:
        try:
            size = dest.stat().st_size
        except OSError:
            size = 0
        logf = self.data / "logs"
        try:
            logf.mkdir(exist_ok=True)
            (logf / f"job-{jid}.log").write_text(result.get("log") or "", encoding="utf-8")
        except OSError as e:
            log.warning("log úlohy %s nelze zapsat: %s", jid, e)
        self.db.update(jid, status="done", filepath=str(dest), filesize=size, finished_at=time.time(), progress=1.0,
                       downloaded=size, total=size, speed=None, eta=None, method=method, error=None, error_kind=None)
        shutil.rmtree(staging, ignore_errors=True)
        done = self.db.get(jid)
        ph = self.phases.get(jid) or {}
        if ph.get("end"):
            now = time.monotonic()
            dl_end = ph.get("post") or ph["end"]
            self.db.record_download(done, True, {"dl": dl_end - ph["t0"], "post": ph["end"] - dl_end, "move": now - ph["end"]})
        else:
            self.db.record_download(done, True)
        self.emit("on_done", done)

    def _finalize(self, jid: int, result: dict, method: str, staging: Path) -> None:
        if self._skip_result(jid, result, method, staging):
            return
        self._complete(jid, self._place(jid, result, method, staging), result, method, staging)

    async def _finalize_async(self, jid: int, result: dict, method: str, staging: Path) -> None:
        if self._skip_result(jid, result, method, staging):
            return
        dest = await asyncio.to_thread(self._place, jid, result, method, staging)
        self._complete(jid, dest, result, method, staging)

    def _failed(self, jid: int, msg: str, kind: str, staging: Path) -> None:
        job = self.db.get(jid)
        s = self.settings.all()
        if kind == "cookies":  # chyba nastavení cookies by shodila celou frontu – pozastavit, úloha zůstane
            self.db.update(jid, status="queued", error=msg, error_kind=kind, speed=None, eta=None)
            self._pause_for_cookies(msg)
            return
        if kind == "disk":  # cíl je plný: fronta je pozastavená (důvod „disk“), hotový soubor zůstává v dočasné složce
            self.db.update(jid, status="queued", not_before=time.time() + 30, error=msg, error_kind=kind, speed=None, eta=None)
            return
        if kind == "target":
            # nedostupný cíl (odpojený NAS) hlídá `_check_target`: fronta se pozastaví a po návratu cíle pustí, pokusy se nepočítají.
            # Když je fronta v chodu a přesun přesto selhává (trvale chybná složka odběru, oprávnění…), po pěti pokusech úloha selže,
            # ale hotové video zůstane v dočasné složce (nemaže se).
            info = json.loads(job["info"]) if job["info"] else {}
            tries = int(info.get("target_tries", 0))
            if self.queue_paused() or tries + 1 < 5:                 # při pozastavené frontě (cíl nedostupný) se pokusy nepočítají
                if not self.queue_paused():
                    info["target_tries"] = tries + 1
                self.db.update(jid, status="queued", not_before=time.time() + 30, error=msg, error_kind=kind, speed=None, eta=None, info=info)
                return
            self.db.update(jid, status="failed", error=f"{msg}. Hotové video zůstalo v dočasné složce: {staging}", error_kind=kind,
                           finished_at=time.time(), speed=None, eta=None)
            failed_job = self.db.get(jid)
            self.db.record_download(failed_job, False)
            if not failed_job["parent_id"]:
                self.emit("on_error", failed_job, msg)
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
        self.db.record_download(job, False)
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
        keep = {k: job[k] for k in ("sub_id", "target_dir", "subdir", "catalog_item_id") if job.get(k)}  # složka odběru a vazba na katalog zůstanou
        new_id, _ = self.add(job["url"], source=job["source"], auto_confirm=True, **keep)
        if job.get("catalog_item_id"):                         # položka katalogu znovu čeká na novou úlohu
            with self.db.conn() as c:
                c.execute("update catalog_items set state='queued', job_id=?, detail_error=null, updated_at=? "
                          "where id=? and state in ('new','queued')", (new_id, time.time(), job["catalog_item_id"]))
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
