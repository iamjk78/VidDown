"""Záloha a obnova dat aplikace (export a import).

Záloha je ZIP: `backup.json` (popis), `viddown.db` (konzistentní snapshot i za běhu), `settings.json`,
`secrets.json`, `cookies.txt`, `archive.txt` a volitelně `thumbs/`. Enginy, logy a dočasné soubory se nezálohují.

Obnova za běhu aplikace se jen připraví (`stage`) a provede se při dalším startu (`apply_pending`), než se
otevře databáze. Dosavadní data se předtím uloží do `<data>/restore/before-<čas>/`, takže jde vrátit.
"""
from __future__ import annotations

import collections
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

FORMAT = 1
FILES = ("settings.json", "secrets.json", "cookies.txt", "archive.txt")
MAX_DB_BYTES = 2 * 1024 ** 3
MAX_TOTAL_BYTES = 4 * 1024 ** 3
KEEP_BEFORE = 3


class BackupError(Exception):
    pass


def _rdir(data: Path) -> Path:
    return Path(data) / "restore"


def _snapshot(db: Path, dst: Path) -> int:
    """Konzistentní kopie databáze (SQLite backup API funguje i za provozu). Vrací verzi schématu."""
    src, out = sqlite3.connect(db), sqlite3.connect(dst)
    try:
        schema = src.execute("pragma user_version").fetchone()[0]
        src.backup(out)
        return schema
    finally:
        out.close()
        src.close()


def _info(db: Path) -> dict:
    """Počty záznamů a tipy na cesty ze snapshotu databáze."""
    c = sqlite3.connect(db)
    try:
        def one(q):
            try:
                return c.execute(q).fetchone()[0]
            except sqlite3.Error:
                return None
        info = {"jobs": one("select count(*) from jobs"),
                "done": one("select count(*) from jobs where status='done'"),
                "subscriptions": one("select count(*) from subscriptions")}
        roots: collections.Counter = collections.Counter()
        try:
            for (fp,) in c.execute("select filepath from jobs where filepath is not null limit 5000"):
                parts = Path(fp).parent.parts[:4]       # např. ('/', 'nas', 'Videa', 'Kanal')
                if len(parts) >= 2:
                    roots[str(Path(*parts[:min(len(parts), 3)]))] += 1
        except sqlite3.Error:
            pass
        info["path_hint"] = roots.most_common(1)[0][0] if roots else None
        return info
    finally:
        c.close()


def create(data: Path, out: Path | None = None, include_thumbs: bool = False) -> Path:
    """Vytvoří zálohu. Bez `out` ji uloží do dočasného souboru (volající ho smaže)."""
    import platform

    from . import __version__
    data = Path(data)
    db = data / "viddown.db"
    if not db.exists():
        raise BackupError("databáze neexistuje, není co zálohovat")
    if out is None:
        fd, name = tempfile.mkstemp(suffix=".zip", prefix="viddown-backup-")
        os.close(fd)
        out = Path(name)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="vdbk-"))
    part = out.with_name(out.name + ".part")
    try:
        snap = tmp / "viddown.db"
        schema = _snapshot(db, snap)
        man = {"format": FORMAT, "created": int(time.time()), "app_version": __version__, "schema_version": schema,
               "platform": platform.system(), "include_thumbs": include_thumbs, **_info(snap)}
        try:   # cílová složka ze zálohovaných nastavení: přesně tu je potřeba při přesunu na jiný stroj přepsat
            man["download_dir"] = json.loads((data / "settings.json").read_text("utf-8")).get("download_dir") or None
        except (OSError, ValueError):
            man["download_dir"] = None
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("backup.json", json.dumps(man, ensure_ascii=False, indent=1))
            zf.write(snap, "viddown.db")
            for name in FILES:
                p = data / name
                if p.is_file():
                    zf.write(p, name)
            if include_thumbs and (data / "thumbs").is_dir():
                for p in sorted((data / "thumbs").iterdir()):
                    if p.is_file():
                        zf.write(p, f"thumbs/{p.name}")
        os.replace(part, out)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        part.unlink(missing_ok=True)


def validate(zip_path: Path) -> dict:
    """Ověří zálohu (struktura, bezpečné názvy, velikost, integrita databáze, verze schématu). Vrací popis."""
    from .db import MIGRATIONS
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        raise BackupError(f"soubor není platná záloha: {e}") from e
    with zf:
        total = 0
        for i in zf.infolist():
            n = i.filename
            ok = n in ("backup.json", "viddown.db") or n in FILES or (
                n.startswith("thumbs/") and "/" not in n[7:] and n[7:] and ".." not in n)
            if not ok and not n.endswith("/"):
                raise BackupError(f"záloha obsahuje nečekaný soubor: {n}")
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise BackupError(f"záloha obsahuje odkaz: {n}")
            if n == "viddown.db" and i.file_size > MAX_DB_BYTES:
                raise BackupError("databáze v záloze je příliš velká")
            total += i.file_size
        if total > MAX_TOTAL_BYTES:
            raise BackupError("záloha je příliš velká")
        try:
            man = json.loads(zf.read("backup.json").decode("utf-8"))
        except (KeyError, ValueError) as e:
            raise BackupError("v záloze chybí backup.json (není to záloha VidDown)") from e
        if int(man.get("format", 0)) > FORMAT:
            raise BackupError("záloha je z novější verze VidDown, aktualizujte aplikaci")
        names = zf.namelist()
        if "viddown.db" not in names:
            raise BackupError("v záloze chybí databáze")
        tmp = Path(tempfile.mkdtemp(prefix="vdbk-"))
        try:
            zf.extract("viddown.db", tmp)
            c = sqlite3.connect(tmp / "viddown.db")
            try:
                integ = c.execute("pragma integrity_check").fetchone()[0]
                have = c.execute("pragma user_version").fetchone()[0]
            except sqlite3.Error as e:
                raise BackupError(f"databáze v záloze je poškozená: {e}") from e
            finally:
                c.close()
            if integ != "ok":
                raise BackupError(f"databáze v záloze je poškozená ({integ})")
            if have > MIGRATIONS[-1][0]:
                raise BackupError(f"záloha je z novější verze (schéma {have}, tato verze umí nejvýše {MIGRATIONS[-1][0]}); "
                                  "aktualizujte aplikaci")
            man.setdefault("schema_version", have)
            man.update({k: v for k, v in _info(tmp / "viddown.db").items() if k not in man})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        man["files"] = [n for n in FILES if n in names]
    return man


def _remap_all(data: Path, old: str, new: str) -> dict:
    """Přepíše začátek cest po přesunu na jiný stroj: historie, cílové složky odběrů a úloh, složky v nastavení."""
    old, new = old.rstrip("/"), new.rstrip("/")
    if not old:
        raise BackupError("stará cesta je prázdná")
    like = (old, len(old) + 1, old + "/")
    n = {"filepath": 0, "target_dir": 0, "folder": 0, "settings": 0}
    c = sqlite3.connect(Path(data) / "viddown.db")
    try:
        def cols(t):
            return {r[1] for r in c.execute(f"pragma table_info({t})")}
        for table, col, key in (("jobs", "filepath", "filepath"), ("jobs", "target_dir", "target_dir"),
                                ("subscriptions", "folder", "folder")):
            if col in cols(table):
                n[key] = c.execute(f"update {table} set {col}=? || substr({col}, ?) where {col} is not null and "
                                   f"({col}=? or substr({col},1,?)=?)", (new, len(old) + 1, old, len(old) + 1, old + "/")).rowcount
        c.commit()
    finally:
        c.close()
    sp = Path(data) / "settings.json"
    if sp.is_file():
        try:
            st = json.loads(sp.read_text("utf-8"))
        except ValueError:
            st = {}
        for k in ("download_dir", "temp_dir"):
            v = st.get(k)
            if isinstance(v, str) and (v == old or v.startswith(old + "/")):
                st[k] = new + v[len(old):]
                n["settings"] += 1
        if n["settings"]:
            sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), "utf-8")
    return n


def apply(data: Path, zip_path: Path, remap: tuple[str, str] | None = None) -> dict:
    """Obnoví data ze zálohy. Dosavadní stav uloží do `<data>/restore/before-<čas>/`. Aplikace nesmí běžet."""
    data = Path(data)
    man = validate(zip_path)
    before = _rdir(data) / f"before-{time.strftime('%Y%m%d-%H%M%S')}"
    before.mkdir(parents=True, exist_ok=True)
    db = data / "viddown.db"
    if db.exists():
        _snapshot(db, before / "viddown.db")
    for name in FILES:
        if (data / name).is_file():
            shutil.copy2(data / name, before / name)
    with zipfile.ZipFile(zip_path) as zf:
        for suf in ("", "-wal", "-shm"):
            Path(str(db) + suf).unlink(missing_ok=True)
        for name in zf.namelist():
            if name == "backup.json" or name.endswith("/"):
                continue
            dest = data / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            if name in ("secrets.json", "cookies.txt"):
                os.chmod(dest, 0o600)
    res = {"ok": True, "at": time.time(), "manifest": man, "before": str(before), "remap": None}
    if remap and remap[0]:
        res["remap"] = _remap_all(data, *remap)
    olds = sorted(p for p in _rdir(data).glob("before-*") if p.is_dir())
    for p in olds[:-KEEP_BEFORE]:
        shutil.rmtree(p, ignore_errors=True)
    return res


# --- obnova za běhu: příprava a provedení při startu -------------------------------------------
def stage(data: Path, zip_path: Path) -> dict:
    """Ověří zálohu a připraví ji k obnově při dalším startu. Nic zatím nemění."""
    man = validate(zip_path)
    d = _rdir(data)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(zip_path, d / "pending.zip")
    (d / "pending.json").write_text(json.dumps({"manifest": man, "remap": None, "staged": time.time()},
                                               ensure_ascii=False), "utf-8")
    return man


def pending(data: Path) -> dict | None:
    d = _rdir(data)
    if not (d / "pending.zip").is_file():
        return None
    try:
        return json.loads((d / "pending.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {"manifest": None, "remap": None}


def set_remap(data: Path, old: str, new: str) -> None:
    d = _rdir(data)
    p = pending(data)
    if p is None:
        raise BackupError("není připravená žádná záloha k obnově")
    p["remap"] = [old.strip(), new.strip()] if old.strip() and new.strip() else None
    (d / "pending.json").write_text(json.dumps(p, ensure_ascii=False), "utf-8")


def clear_pending(data: Path) -> None:
    for n in ("pending.zip", "pending.json"):
        (_rdir(data) / n).unlink(missing_ok=True)


def last_result(data: Path) -> dict | None:
    try:
        return json.loads((_rdir(data) / "last.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None


def apply_pending(data: Path) -> dict | None:
    """Volá se při startu před otevřením databáze. Provede připravenou obnovu a zapíše výsledek."""
    data = Path(data)
    p = pending(data)
    if p is None:
        return None
    zp = _rdir(data) / "pending.zip"
    try:
        remap = tuple(p["remap"]) if p.get("remap") else None
        res = apply(data, zp, remap)
    except Exception as e:  # noqa: BLE001 – chybná záloha nesmí zabránit startu; zůstanou stará data
        res = {"ok": False, "at": time.time(), "error": str(e), "manifest": p.get("manifest")}
    clear_pending(data)
    (_rdir(data)).mkdir(parents=True, exist_ok=True)
    (_rdir(data) / "last.json").write_text(json.dumps(res, ensure_ascii=False), "utf-8")
    return res
