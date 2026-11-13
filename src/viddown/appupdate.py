"""Aktualizace kódu aplikace zevnitř (PLAN.md kap. 18).

Kód aplikace (balíček `viddown`, čistý Python) se instaluje do `<data>/app/<verze>/` vedle obrazu.
Spouštěč (`bootstrap.py`) při startu vybere aktivní verzi; nová verze projde samotestem, po přepnutí běží
ve zkušební době a když nenaběhne zdravě, vrátí se předchozí verze a vadná se přeskočí.

Stav je v `<data>/app/state.json`:
  current      aktivní nainstalovaná verze (None = verze zabudovaná v obraze)
  previous     verze, na kterou se vrátíme (None = zabudovaná)
  skipped      {verze: {reason, at}} – vadné verze, které se už nezkouší
  probation    {version, attempts, since, db_backup, schema_before} nebo None
  events       posledních 30 událostí pro GUI a Telegram
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

log = logging.getLogger("viddown.appupdate")

MAX_FAILED_STARTS = 2        # po tolika startech, které nedosáhly „zdravého“ stavu, se vrátí předchozí verze
HEALTHY_AFTER = 120.0        # sekund běhu, po kterých se nová verze považuje za zdravou
KEEP_VERSIONS = 3
MAX_ZIP_BYTES = 80 * 1024 * 1024
MAX_UNPACKED_BYTES = 250 * 1024 * 1024
VER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class UpdateError(Exception):
    pass


def vkey(v: str | None) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")) or (0,)


def image_api() -> int:
    """Co umí obraz (zvyšuje se při změně závislostí nebo Dockerfile). Spouštěč ho předá proměnnou prostředí."""
    env = os.environ.get("VIDDOWN_IMAGE_API")
    if env and env.isdigit():
        return int(env)
    from .bootstrap import IMAGE_API
    return IMAGE_API


def baseline_version() -> str:
    """Verze zabudovaná v obraze (ne verze právě běžícího kódu z aktualizace)."""
    from . import __version__
    return os.environ.get("VIDDOWN_BASE_VERSION") or __version__


def baseline_schema() -> int:
    env = os.environ.get("VIDDOWN_BASE_SCHEMA")
    if env and env.isdigit():
        return int(env)
    from .db import MIGRATIONS
    return MIGRATIONS[-1][0]


def _user_version(db: Path) -> int | None:
    if not db.exists():
        return None
    try:
        c = sqlite3.connect(db)
        try:
            return c.execute("pragma user_version").fetchone()[0]
        finally:
            c.close()
    except sqlite3.Error:
        return None


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class AppStore:
    def __init__(self, data: Path):
        self.data = Path(data)
        self.root = self.data / "app"
        self.file = self.root / "state.json"
        self.db_path = self.data / "viddown.db"

    # --- stav ---------------------------------------------------------------------------------
    def state(self) -> dict:
        d = {"current": None, "previous": None, "skipped": {}, "probation": None, "events": []}
        try:
            d.update(json.loads(self.file.read_text("utf-8")))
        except (OSError, ValueError):
            pass
        return d

    def save(self, st: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.file)

    @staticmethod
    def _event(st: dict, kind: str, version: str | None, msg: str) -> None:
        st["events"] = (list(st.get("events") or []) + [{"t": time.time(), "kind": kind, "version": version, "msg": msg}])[-30:]
        log.info("aktualizace aplikace: %s %s – %s", kind, version or "", msg)

    def path(self, ver: str) -> Path:
        if not VER_RE.match(ver or ""):
            raise UpdateError(f"neplatná verze: {ver!r}")
        return self.root / ver

    def installed(self) -> list[str]:
        if not self.root.is_dir():
            return []
        out = [p.name for p in self.root.iterdir() if VER_RE.match(p.name) and (p / "viddown" / "__init__.py").exists()]
        return sorted(out, key=vkey)

    def manifest(self, ver: str) -> dict:
        try:
            return json.loads((self.path(ver) / "manifest.json").read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    # --- instalace ----------------------------------------------------------------------------
    def install_zip(self, zip_path: Path, expect_sha256: str | None = None) -> str:
        """Ověří a rozbalí archiv vydání do `<data>/app/<verze>/`. Vrací verzi."""
        zip_path = Path(zip_path)
        if zip_path.stat().st_size > MAX_ZIP_BYTES:
            raise UpdateError("archiv je příliš velký")
        if expect_sha256 and _sha256(zip_path).lower() != expect_sha256.lower():
            raise UpdateError("kontrolní součet archivu nesouhlasí")
        try:
            zf = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile as e:
            raise UpdateError(f"archiv je poškozený: {e}") from e
        with zf:
            total = 0
            for i in zf.infolist():
                n = i.filename
                if n.startswith("/") or ".." in Path(n).parts or "\\" in n:
                    raise UpdateError(f"nebezpečná cesta v archivu: {n}")
                if (i.external_attr >> 16) & 0o170000 == 0o120000:
                    raise UpdateError(f"archiv obsahuje odkaz: {n}")
                total += i.file_size
            if total > MAX_UNPACKED_BYTES:
                raise UpdateError("rozbalený archiv je příliš velký")
            try:
                man = json.loads(zf.read("manifest.json").decode("utf-8"))
            except (KeyError, ValueError) as e:
                raise UpdateError("v archivu chybí platný manifest.json") from e
            ver = str(man.get("version", ""))
            if not VER_RE.match(ver):
                raise UpdateError(f"manifest: neplatná verze {ver!r}")
            req = int(man.get("requires_image_api", 1))
            if req > image_api():
                raise UpdateError(f"verze {ver} vyžaduje novější obraz (API {req}, obraz má {image_api()})")
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / f".tmp-{ver}"
            shutil.rmtree(tmp, ignore_errors=True)
            zf.extractall(tmp)
        init = tmp / "viddown" / "__init__.py"
        if not init.exists() or f'__version__ = "{ver}"' not in init.read_text("utf-8"):
            shutil.rmtree(tmp, ignore_errors=True)
            raise UpdateError("obsah archivu neodpovídá verzi v manifestu")
        dest = self.path(ver)
        st = self.state()
        if dest.exists():
            if ver in (st["current"], st["previous"]):
                shutil.rmtree(tmp, ignore_errors=True)
                raise UpdateError(f"verze {ver} je právě používána")
            shutil.rmtree(dest)
        os.replace(tmp, dest)
        self._event(st, "installed", ver, "rozbaleno")
        self.save(st)
        return ver

    def selftest(self, ver: str, skip_engines: bool = False, timeout: float = 240) -> tuple[bool, dict]:
        """Spustí samotest nové verze v odděleném procesu (nad kopií databáze)."""
        cmd = [sys.executable, "-m", "viddown.selftest", "--data", str(self.data), "--expect", ver]
        if skip_engines:
            cmd.append("--skip-engines")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.path(ver)) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["VIDDOWN_IMAGE_API"] = str(image_api())
        env["VIDDOWN_BASE_VERSION"] = baseline_version()
        env["VIDDOWN_BASE_SCHEMA"] = str(baseline_schema())
        try:
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, cwd=str(self.root))
        except subprocess.TimeoutExpired:
            return False, {"ok": False, "checks": [{"name": "samotest", "ok": False, "detail": f"vypršel časový limit {int(timeout)} s"}]}
        report = None
        for line in reversed((r.stdout or "").strip().splitlines()):
            try:
                report = json.loads(line)
                break
            except ValueError:
                continue
        if report is None:
            tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["bez výstupu"])[-1]
            report = {"ok": False, "checks": [{"name": "samotest", "ok": False, "detail": tail[:300]}]}
        return bool(report.get("ok")) and r.returncode == 0, report

    # --- přepnutí a návrat --------------------------------------------------------------------
    def _backup_db(self, ver: str) -> tuple[str | None, int | None]:
        if not self.db_path.exists():
            return None, None
        self.root.mkdir(parents=True, exist_ok=True)
        dst = self.root / f"db-before-{ver}.sqlite"
        src = sqlite3.connect(self.db_path)
        out = sqlite3.connect(dst)
        try:
            schema = src.execute("pragma user_version").fetchone()[0]
            src.backup(out)
        finally:
            out.close()
            src.close()
        for old in self.root.glob("db-before-*.sqlite"):
            if old != dst:
                old.unlink(missing_ok=True)
        return str(dst), schema

    def activate(self, ver: str) -> None:
        """Přepne na nainstalovanou verzi. Uloží zálohu databáze a zahájí zkušební dobu."""
        if ver not in self.installed():
            raise UpdateError(f"verze {ver} není nainstalována")
        if vkey(ver) <= vkey(baseline_version()):
            raise UpdateError(f"verze {ver} není novější než verze v obraze ({baseline_version()})")
        st = self.state()
        if st["current"] == ver:
            raise UpdateError(f"verze {ver} už je aktivní")
        bak, schema = self._backup_db(ver)
        st["previous"], st["current"] = st["current"], ver
        st["skipped"].pop(ver, None)
        st["probation"] = {"version": ver, "attempts": 0, "since": time.time(), "db_backup": bak, "schema_before": schema}
        self._event(st, "switched", ver, f"přepnuto z {st['previous'] or baseline_version() + ' (obraz)'}")
        self.save(st)
        self.prune()

    def _schema_of(self, ver: str | None) -> int | None:
        if ver is None:
            return baseline_schema()
        s = self.manifest(ver).get("schema_version")
        return int(s) if isinstance(s, int) else None

    def _restore_db(self, ver: str, backup: str) -> None:
        failed = self.data / f"viddown.db.failed-{ver}"
        failed.unlink(missing_ok=True)
        shutil.move(str(self.db_path), str(failed))
        for suf in ("-wal", "-shm"):
            Path(str(self.db_path) + suf).unlink(missing_ok=True)
        shutil.copy2(backup, self.db_path)

    def rollback(self, reason: str, restore_db: bool = False, auto: bool = False) -> dict:
        """Vrátí předchozí verzi a aktuální označí jako přeskočenou.

        Když nová verze databázi migrovala na novější schéma, než zná předchozí verze, je potřeba obnovit zálohu
        (starší kód novější schéma odmítne). Automatický návrat ve zkušební době to dělá sám; ruční návrat jen
        s `restore_db=True`, protože by se ztratila data vzniklá od přepnutí."""
        st = self.state()
        cur = st["current"]
        if not cur:
            raise UpdateError("žádná aktualizovaná verze není aktivní")
        prev = st["previous"]
        pr = st["probation"] if st.get("probation") and st["probation"].get("version") == cur else None
        target, have = self._schema_of(prev), _user_version(self.db_path)
        restored = False
        if target is not None and have is not None and have > target:
            backup = (pr or {}).get("db_backup")
            if not (auto or restore_db):
                raise UpdateError(f"databáze má schéma {have}, verze {prev or baseline_version()} umí nejvýše {target}. "
                                  "Návrat vyžaduje obnovu zálohy databáze a ztrátu dat od přepnutí (--restore-db).")
            if not backup or not Path(backup).exists():
                raise UpdateError("databáze má novější schéma a záloha před přepnutím chybí")
            self._restore_db(cur, backup)
            restored = True
        st["skipped"][cur] = {"reason": reason, "at": time.time()}
        st["current"], st["previous"], st["probation"] = prev, None, None
        self._event(st, "rolled_back", cur, f"{reason}; zpět na {prev or baseline_version() + ' (obraz)'}"
                    + ("; databáze obnovena ze zálohy" if restored else ""))
        self.save(st)
        return {"from": cur, "to": prev, "restored_db": restored}

    def begin_start(self, count: bool = True) -> Path | None:
        """Volá spouštěč při startu. Vrací složku verze, která se má spustit (None = verze z obrazu).
        Počítá starty ve zkušební době a po `MAX_FAILED_STARTS` nezdravých startech vrátí předchozí verzi."""
        for _ in range(4):
            st = self.state()
            cur = st["current"]
            if not cur:
                return None
            if vkey(cur) <= vkey(baseline_version()):
                st["current"], st["previous"], st["probation"] = None, None, None
                self._event(st, "superseded", cur, f"obraz ({baseline_version()}) je stejně nový nebo novější")
                self.save(st)
                return None
            if cur not in self.installed():
                self.rollback(f"chybí soubory verze {cur}", auto=True)
                continue
            pr = st.get("probation")
            if pr and pr.get("version") == cur and count:
                if pr["attempts"] >= MAX_FAILED_STARTS:
                    self.rollback(f"verze nenaběhla zdravě ({pr['attempts']} neúspěšné starty)", auto=True)
                    continue
                pr["attempts"] += 1
                self.save(st)
            return self.path(cur)
        return None

    def mark_healthy(self, ver: str) -> bool:
        st = self.state()
        pr = st.get("probation")
        if not pr or pr.get("version") != ver:
            return False
        st["probation"] = None
        self._event(st, "healthy", ver, "zkušební doba proběhla bez chyby")
        self.save(st)
        return True

    def note_clean_stop(self, ver: str) -> None:
        """Řádné ukončení (např. ruční restart) ve zkušební době není selhání, nezapočítá se."""
        st = self.state()
        pr = st.get("probation")
        if pr and pr.get("version") == ver and pr["attempts"] > 0:
            pr["attempts"] -= 1
            self.save(st)

    # --- správa verzí -------------------------------------------------------------------------
    def skip(self, ver: str, reason: str) -> None:
        st = self.state()
        st["skipped"][ver] = {"reason": reason, "at": time.time()}
        self._event(st, "skipped", ver, reason)
        self.save(st)

    def unskip(self, ver: str) -> bool:
        st = self.state()
        if st["skipped"].pop(ver, None) is None:
            return False
        self.save(st)
        return True

    def remove(self, ver: str) -> None:
        st = self.state()
        if ver in (st["current"], st["previous"]):
            raise UpdateError(f"verze {ver} je používána")
        shutil.rmtree(self.path(ver), ignore_errors=True)

    def prune(self, keep: int = KEEP_VERSIONS) -> list[str]:
        st = self.state()
        protected = {v for v in (st["current"], st["previous"]) if v}
        removed = []
        for v in reversed(self.installed()):
            if v in protected:
                continue
            if len(protected) < keep:
                protected.add(v)
            else:
                shutil.rmtree(self.path(v), ignore_errors=True)
                removed.append(v)
        return removed

    def status(self) -> dict:
        st = self.state()
        return {"baseline": baseline_version(), "running": os.environ.get("VIDDOWN_APP_ACTIVE") or baseline_version(),
                "current": st["current"], "previous": st["previous"], "installed": self.installed(),
                "skipped": st["skipped"], "probation": st["probation"], "events": st["events"][-8:],
                "image_api": image_api()}


def pack(out: Path, version: str | None = None, requires_image_api: int | None = None,
         commit: str | None = None) -> dict:
    """Sbalí běžící zdrojový kód (balíček `viddown`) do archivu vydání s `manifest.json`.
    `version` přepíše `__version__` v archivu (pro zkoušky). Vrací manifest doplněný o `sha256` a `file`."""
    import viddown
    from .db import MIGRATIONS
    src = Path(viddown.__file__).parent
    ver = version or viddown.__version__
    if not VER_RE.match(ver):
        raise UpdateError(f"neplatná verze: {ver!r}")
    man = {"version": ver, "requires_image_api": requires_image_api if requires_image_api is not None else image_api(),
           "schema_version": MIGRATIONS[-1][0], "commit": commit, "created": int(time.time())}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(man, ensure_ascii=False, indent=1))
        for p in sorted(src.rglob("*")):
            if p.is_dir() or "__pycache__" in p.parts or p.suffix in (".pyc", ".pyo"):
                continue
            rel = p.relative_to(src.parent).as_posix()
            if rel == "viddown/__init__.py" and version:
                text = re.sub(r'__version__ = "[^"]*"', f'__version__ = "{ver}"', p.read_text("utf-8"))
                zf.writestr(rel, text)
            else:
                zf.write(p, rel)
    man["sha256"] = _sha256(out)
    man["file"] = str(out)
    return man


async def health_task(data: Path, stop: asyncio.Event, after: float | None = None) -> None:
    """Po `HEALTHY_AFTER` sekundách běhu označí aktualizovanou verzi za zdravou (ukončí zkušební dobu)."""
    ver = os.environ.get("VIDDOWN_APP_ACTIVE")
    if not ver:
        return
    store = AppStore(data)
    try:
        await asyncio.wait_for(stop.wait(), timeout=HEALTHY_AFTER if after is None else after)
    except asyncio.TimeoutError:
        await asyncio.to_thread(store.mark_healthy, ver)
    else:
        await asyncio.to_thread(store.note_clean_stop, ver)
