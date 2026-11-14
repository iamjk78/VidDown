"""Aktualizace aplikace za běhu (PLAN.md kap. 18, etapa 3): stav pro GUI a Telegram, kontrola podle rozvrhu,
oznámení a automatický režim.

Režimy (`app_update_mode`): `off` – nic; `notify` (výchozí) – jen oznámit a nabídnout tlačítko; `auto` – stáhnout,
otestovat a po doběhnutí stahování restartovat. Restart nikdy nepřeruší běžící stahování: fronta se měkce pozastaví
(rozpracované doběhnou), po restartu se obnoví.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from . import appupdate as au
from .config import APP_UPDATE_HOURS

log = logging.getLogger("viddown.updater")

RETRY_AFTER = 3600          # po chybě kontroly další pokus za hodinu
WAIT_MAX = 6 * 3600         # nejdéle tak dlouho se čeká na doběhnutí stahování
POLL = 5
ROLLBACK_BANNER_DAYS = 14
_APPLYING = {"on": False}
_BUSY = threading.Lock()
_BANNER_CACHE: dict = {"t": 0.0, "v": None}


def store(st) -> au.AppStore:
    return au.AppStore(st.data)


def mode(st) -> str:
    m = st.settings.get("app_update_mode")
    return m if m in ("off", "notify", "auto") else "notify"


def hours(st) -> int:
    h = st.settings.get("app_update_hours")
    return h if h in APP_UPDATE_HOURS else 24


def prepared(s: dict) -> bool:
    """Nová verze je nainstalovaná a otestovaná, ale ještě neběží (čeká na restart)."""
    return bool(s["current"] and s["current"] != s["running"])


def _banner(s: dict) -> dict | None:
    if _APPLYING["on"]:
        return {"kind": "applying", "version": s["current"]}
    if prepared(s):
        return {"kind": "prepared", "version": s["current"]}
    now = time.time()
    for e in reversed(s["events"]):
        if e["kind"] == "rolled_back" and e["t"] > s.get("dismissed", 0) and now - e["t"] < ROLLBACK_BANNER_DAYS * 86400:
            return {"kind": "rolled_back", "version": e["version"], "msg": e["msg"], "t": e["t"]}
    chk = s.get("check") or {}
    if chk.get("status") == "available":
        return {"kind": "available", "version": chk.get("version")}
    return None


def status(st) -> dict:
    s = store(st).status()
    s.update(repo=st.settings.get("app_update_repo"), mode=mode(st), hours=hours(st), token_set=bool(st.secrets.app_update_token),
             prepared=prepared(s), applying=_APPLYING["on"])
    s["banner"] = _banner(s)
    return s


def banner_cached(st, ttl: float = 3.0) -> dict | None:
    """Pro každosekundový stav do GUI: soubor se stavem se čte nejvýš jednou za pár sekund."""
    now = time.time()
    if now - _BANNER_CACHE["t"] > ttl:
        try:
            _BANNER_CACHE.update(t=now, v=_banner(store(st).status()))
        except Exception:  # noqa: BLE001
            _BANNER_CACHE.update(t=now, v=None)
    return _BANNER_CACHE["v"]


def _guard():
    if not _BUSY.acquire(blocking=False):
        raise au.UpdateError("Aktualizace už probíhá.")


def do_check(st) -> dict:
    _guard()
    try:
        au.check(store(st), st.settings.get("app_update_repo"), st.secrets.app_update_token)
    finally:
        _BUSY.release()
        _BANNER_CACHE["t"] = 0.0
    return status(st)


def do_update(st, force: bool = False, skip_engines: bool = False) -> dict:
    """Stáhne, ověří, otestuje a připraví novou verzi (spustí se po restartu)."""
    _guard()
    try:
        res = au.update(store(st), st.settings.get("app_update_repo"), st.secrets.app_update_token, force=force,
                        skip_engines=skip_engines)
    finally:
        _BUSY.release()
        _BANNER_CACHE["t"] = 0.0
    return {"result": {k: v for k, v in res.items() if k != "report"}, "status": status(st)}


def do_rollback(st, restore_db: bool = False) -> dict:
    _guard()                                                      # návrat nesmí běžet souběžně s kontrolou nebo aktualizací (přepsal by jejich stav)
    try:
        store(st).rollback("ruční návrat", restore_db=restore_db)
    finally:
        _BUSY.release()
        _BANNER_CACHE["t"] = 0.0
    return status(st)


def request_restart(st) -> None:
    """Řádně ukončí aplikaci (v Dockeru ji kontejner znovu spustí). Volat z vlákna s běžící smyčkou událostí."""
    stop = getattr(st, "stop", None)
    if stop is None:
        raise au.UpdateError("Restart není v tomto režimu k dispozici")
    st.restart = True
    asyncio.get_running_loop().call_later(0.5, stop.set)


def notify(st, key: str, **kw) -> bool:
    bot = getattr(st, "bot", None)
    if bot is None or getattr(bot, "state", None) != "ok":
        return False
    bot.notify_threadsafe(key, **kw)
    return True


# --- restart až po doběhnutí stahování ----------------------------------------------------------
def _resume(st) -> None:
    if st.db.kv_get("update_resume", False):
        st.db.kv_set("queue_paused", False)
        st.db.kv_set("queue_pause_reason", None)
        st.db.kv_set("queue_pause_hard", False)
    st.db.kv_set("update_resume", False)


def startup(st) -> None:
    """Po restartu kvůli aktualizaci obnoví frontu, kterou jsme před restartem pozastavili my."""
    _APPLYING["on"] = False
    if st.db.kv_get("update_resume", False):
        _resume(st)
        log.info("po aktualizaci obnovuji frontu")


_TASKS: set[asyncio.Task] = set()


def spawn_apply(st) -> asyncio.Task:
    """Spustí `apply_when_idle` na pozadí a drží si odkaz na úlohu (jinak ji může uklidit GC) i její případnou výjimku v logu."""
    task = asyncio.get_running_loop().create_task(apply_when_idle(st))
    _TASKS.add(task)

    def done(t: asyncio.Task) -> None:
        _TASKS.discard(t)
        if not t.cancelled() and t.exception() is not None:
            log.error("použití aktualizace selhalo", exc_info=t.exception())
    task.add_done_callback(done)
    return task


async def apply_when_idle(st) -> str:
    """Měkce pozastaví frontu (běžící stahování doběhnou), počká a restartuje. Vrací: restarting | postponed | cancelled | busy."""
    if _APPLYING["on"]:
        return "busy"
    s = status(st)
    if not s["prepared"]:
        raise au.UpdateError("Žádná nová verze není připravená k restartu.")
    _APPLYING["on"] = True
    result = "restarting"
    try:
        db = st.db
        paused_before = bool(db.kv_get("queue_paused", False))
        if not paused_before:
            db.kv_set("queue_paused", True)
            db.kv_set("queue_pause_reason", "user")
            db.kv_set("queue_pause_hard", False)
        db.kv_set("update_resume", not paused_before)        # jen když jsme frontu pozastavili my
        started = time.time()
        while st.runner.running:
            await asyncio.sleep(POLL)
            if not db.kv_get("queue_paused", False):         # uživatel frontu obnovil: chce stahovat, restart zrušen
                db.kv_set("update_resume", False)
                result = "cancelled"
                return result
            if time.time() - started > WAIT_MAX:
                _resume(st)
                result = "postponed"
                notify(st, "app_update_postponed", version=s["current"])
                return result
        request_restart(st)
        return result
    finally:
        if result != "restarting":
            _APPLYING["on"] = False
            _BANNER_CACHE["t"] = 0.0


# --- oznámení do Telegramu ----------------------------------------------------------------------
def announce_pending(st) -> None:
    """Pošle (jednou) oznámení o nové verzi a o výsledku aktualizace (zdravý start, návrat)."""
    bot = getattr(st, "bot", None)
    if bot is None or getattr(bot, "state", None) != "ok":
        return
    ast = store(st)
    s = ast.state()
    events = s.get("events") or []
    if "announced" not in s:                      # první spuštění: staré události neoznamovat
        ast.update_state(announced=max([e["t"] for e in events] or [0]))
        return
    chk = s.get("check") or {}
    if mode(st) == "notify" and chk.get("status") == "available" and s.get("notified_available") != chk.get("version"):
        if notify(st, "app_update_available", version=chk["version"], current=s["current"] or au.baseline_version()):
            ast.update_state(notified_available=chk["version"])
    last = s["announced"]
    for e in events:
        if e["t"] <= last or e["kind"] not in ("healthy", "rolled_back"):
            continue
        ok = notify(st, "app_update_done", version=e["version"]) if e["kind"] == "healthy" else \
            notify(st, "app_update_rolled_back", version=e["version"], reason=e["msg"])
        if ok:
            last = max(last, e["t"])
    if last != s["announced"]:
        ast.update_state(announced=last)


# --- rozvrh na pozadí ---------------------------------------------------------------------------
def check_due(st) -> bool:
    chk = store(st).state().get("check") or {}
    age = time.time() - chk.get("at", 0)
    if chk.get("status") == "error":
        return age >= RETRY_AFTER
    return age >= hours(st) * 3600


async def auto_update(st) -> None:
    """Automatický režim: připraví novou verzi (když ještě není) a restartuje po doběhnutí stahování."""
    s = status(st)
    if not s["prepared"]:
        chk = s.get("check") or {}
        if chk.get("status") != "available":
            return
        try:
            r = await asyncio.to_thread(do_update, st)
        except au.UpdateError as e:
            log.warning("automatická aktualizace: %s", e)
            notify(st, "app_update_failed", version=chk.get("version"), error=str(e))
            return
        notify(st, "app_update_auto", version=r["result"].get("version"))
    await apply_when_idle(st)


async def tick(st) -> None:
    await asyncio.to_thread(announce_pending, st)
    if mode(st) == "off" or not await asyncio.to_thread(check_due, st):
        return
    try:
        await asyncio.to_thread(do_check, st)
    except au.UpdateError as e:
        log.info("kontrola nové verze: %s", e)
        return
    if mode(st) == "auto":
        await auto_update(st)


async def task(st, stop: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(stop.wait(), 40)
    except asyncio.TimeoutError:
        pass
    while not stop.is_set():
        try:
            await tick(st)
        except Exception:  # noqa: BLE001
            log.exception("aktualizace aplikace: neočekávaná chyba")
        try:
            await asyncio.wait_for(stop.wait(), 60)
        except asyncio.TimeoutError:
            pass
