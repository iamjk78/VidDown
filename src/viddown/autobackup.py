"""Automatické zálohy podle rozvrhu (PLAN.md kap. 19).

Záloha je šifrovaný soubor `VidDown_<datum>_<čas>.dtb` ve zvolené složce. Po úspěšném vytvoření a ověření se starší
zálohy nad zadaný počet smažou; maže se jen to, co má přesně takový název. Při chybě (např. nepřipojený NAS) se nic
nemaže a po hodině se to zkusí znovu.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path

from . import backup
from .config import AUTO_BACKUP_HOURS

log = logging.getLogger("viddown.autobackup")

RETRY_AFTER = 3600           # po chybě další pokus za hodinu
NOTIFY_EVERY = 24 * 3600     # zpráva o selhání do Telegramu nejvýš jednou denně
NAME_RE = re.compile(r"^VidDown_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(?:-\d{2}(?:_\d+)?)?\.dtb$")
KV = "auto_backup_state"
_LOCK = threading.Lock()


def folder(data: Path, settings) -> Path:
    d = str(settings.get("auto_backup_dir") or "").strip()
    return Path(d).expanduser() if d else Path(data) / "backups"


def list_backups(fold: Path) -> list[dict]:
    """Zálohy ve složce (jen soubory s naším názvem), nejnovější první."""
    out = []
    try:
        for p in fold.iterdir():
            if NAME_RE.match(p.name) and p.is_file():
                st = p.stat()
                out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    except OSError:
        return []
    return sorted(out, key=lambda x: (x["mtime"], x["name"]), reverse=True)


def _unique_path(fold: Path) -> Path:
    p, n = fold / backup.default_name(), 0
    while p.exists():       # dvě zálohy ve stejné minutě
        n += 1
        base = f"{backup.default_name()[:-4]}-{time.strftime('%S')}"
        p = fold / (f"{base}.dtb" if n == 1 else f"{base}_{n}.dtb")
    return p


def prune(fold: Path, keep: int, protect: Path) -> list[str]:
    """Smaže nejstarší zálohy nad `keep`; právě vytvořená se nikdy nesmaže a počítá se mezi uchované."""
    others = [b for b in list_backups(fold) if b["name"] != protect.name]
    removed = []
    for b in others[max(keep - 1, 0):]:
        try:
            (fold / b["name"]).unlink()
            removed.append(b["name"])
        except OSError as e:
            log.warning("záloha %s nejde smazat: %s", b["name"], e)
    return removed


def _cleanup_stale(fold: Path) -> None:
    """Zbytky přerušených záloh (starší než den)."""
    try:
        for p in fold.iterdir():
            if p.name.startswith("VidDown_") and p.name.endswith((".dtb.enc", ".dtb.part")) \
                    and time.time() - p.stat().st_mtime > 86400:
                p.unlink(missing_ok=True)
    except OSError:
        pass


def state(db) -> dict:
    s = db.kv_get(KV, {})
    return s if isinstance(s, dict) else {}


def _hours(settings) -> int:
    h = settings.get("auto_backup_hours")
    return h if h in AUTO_BACKUP_HOURS else 24


def due(settings, db, now: float | None = None) -> bool:
    if not settings.get("auto_backup"):
        return False
    now = now or time.time()
    s = state(db)
    if s.get("error") and now - s.get("last_try", 0) < RETRY_AFTER:
        return False
    if s.get("dir") != str(folder(db.path.parent, settings)):
        return True                                        # nová složka: zálohovat hned
    return now - (s.get("last_ok") or 0) >= _hours(settings) * 3600


def next_due(settings, db) -> float | None:
    if not settings.get("auto_backup"):
        return None
    s = state(db)
    if s.get("dir") != str(folder(db.path.parent, settings)):
        return time.time()
    t = (s.get("last_ok") or 0) + _hours(settings) * 3600
    if s.get("error"):
        t = max(t, s.get("last_try", 0) + RETRY_AFTER)
    return t


def run_once(data: Path, settings, db) -> dict:
    fold = folder(data, settings)
    fold.mkdir(parents=True, exist_ok=True)
    _cleanup_stale(fold)
    out = _unique_path(fold)
    backup.create(data, out, include_thumbs=False, encrypt=True)
    try:
        backup.validate(out)                               # nová záloha se musí dát přečíst, než se smaže cokoli starého
    except backup.BackupError:
        out.unlink(missing_ok=True)
        raise
    removed = prune(fold, int(settings.get("auto_backup_keep") or 5), out)
    return {"file": out.name, "size": out.stat().st_size, "removed": removed}


def run(st) -> dict:
    """Vytvoří zálohu hned (rozvrh i tlačítko) a zapíše výsledek. Při chybě vyhodí BackupError."""
    if not _LOCK.acquire(blocking=False):
        raise backup.BackupError("záloha právě probíhá")
    try:
        prev = state(st.db)
        now = time.time()
        try:
            res = run_once(st.data, st.settings, st.db)
        except (backup.BackupError, OSError, sqlite3.Error) as e:
            msg = str(e) or type(e).__name__
            new = {**prev, "last_try": now, "error": msg, "dir": str(folder(st.data, st.settings))}
            bot = getattr(st, "bot", None)
            if bot and (not prev.get("error") or now - prev.get("notified", 0) > NOTIFY_EVERY):
                bot.notify_threadsafe("backup_fail", error=msg)
                new["notified"] = now
            st.db.kv_set(KV, new)
            log.warning("automatická záloha selhala: %s", msg)
            raise backup.BackupError(msg) from e
        st.db.kv_set(KV, {"last_ok": now, "last_try": now, "error": None, "notified": 0, "dir": str(folder(st.data, st.settings)),
                          "file": res["file"], "size": res["size"], "removed": res["removed"]})
        log.info("automatická záloha: %s (%d kB), smazáno starších: %d", res["file"], res["size"] // 1024, len(res["removed"]))
        return res
    finally:
        _LOCK.release()


def tick(st) -> None:
    """Jedna kontrola rozvrhu: když je záloha na řadě, vytvoří ji. Chyba je zapsaná ve stavu a v logu."""
    try:
        if due(st.settings, st.db):
            run(st)
    except backup.BackupError:
        pass


async def task(st, stop: asyncio.Event) -> None:
    """Smyčka na pozadí: jednou za minutu zkontroluje, zda je záloha na řadě."""
    try:
        await asyncio.wait_for(stop.wait(), 30)             # nechat aplikaci nastartovat
    except asyncio.TimeoutError:
        pass
    while not stop.is_set():
        try:
            await asyncio.to_thread(tick, st)
        except Exception:  # noqa: BLE001
            log.exception("automatické zálohy: neočekávaná chyba")
        try:
            await asyncio.wait_for(stop.wait(), 60)
        except asyncio.TimeoutError:
            pass
