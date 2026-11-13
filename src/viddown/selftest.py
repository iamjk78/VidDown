"""Samotest nové verze kódu (spouští ho `AppStore.selftest` v odděleném procesu s PYTHONPATH na novou verzi).

Nic nemění v ostrých datech: databázi zkopíruje do dočasné složky a migraci i aplikaci vyzkouší tam.
Výstup: poslední řádek je JSON {"ok": bool, "checks": [{name, ok, detail}]}.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def run(real_data: Path, expect: str | None = None, skip_engines: bool = False) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "") -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    import viddown
    add("verze", expect is None or viddown.__version__ == expect, f"kód hlásí {viddown.__version__}, čekáno {expect}")

    failed = []
    for m in pkgutil.walk_packages(viddown.__path__, "viddown."):
        if m.name.endswith((".selftest", ".__main__")):      # __main__ by spustil aplikaci
            continue
        try:
            importlib.import_module(m.name)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{m.name}: {type(e).__name__}: {e}")
    add("moduly", not failed, "; ".join(failed[:3]) or "všechny se načetly")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        tmp = Path(t)
        src = real_data / "viddown.db"
        schema_before = None
        if src.exists():
            a, b = sqlite3.connect(src), sqlite3.connect(tmp / "viddown.db")
            try:
                schema_before = a.execute("pragma user_version").fetchone()[0]
                a.backup(b)
            finally:
                a.close()
                b.close()
        eng = real_data / "engines"
        if eng.exists():
            os.symlink(eng, tmp / "engines")
        os.environ["VIDDOWN_DATA"] = str(tmp)
        os.environ.pop("VIDDOWN_PASSWORD", None)
        try:
            from viddown.db import DB, MIGRATIONS
            db = DB(tmp / "viddown.db")      # DB při otevření provede migrace nad kopií
            with db.conn() as c:
                integ = c.execute("pragma integrity_check").fetchone()[0]
            add("databáze", integ == "ok" and db.schema_version == MIGRATIONS[-1][0],
                f"schéma {schema_before} -> {db.schema_version}, kontrola {integ}")
        except Exception as e:  # noqa: BLE001
            add("databáze", False, f"{type(e).__name__}: {e}")
            return {"ok": False, "checks": checks}
        st = None
        try:
            from fastapi.testclient import TestClient

            from viddown.daemon import AppState
            from viddown.server import create_app
            st = AppState()
            client = TestClient(create_app(st))
            r1, r2 = client.get("/api/session"), client.get("/api/state")
            add("aplikace", r1.status_code == 200 and r2.status_code == 200,
                f"/api/session {r1.status_code}, /api/state {r2.status_code}")
        except Exception as e:  # noqa: BLE001
            add("aplikace", False, f"{type(e).__name__}: {e}")
        if not skip_engines and st is not None:
            for name, arg in (("ffmpeg", "-version"), ("yt-dlp", "--version")):
                try:
                    binp = st.engines.get(name).bin_path()
                    ok = False
                    if binp:
                        r = subprocess.run([binp, arg], capture_output=True, text=True, timeout=30)
                        ok = r.returncode == 0
                    add(f"engine {name}", ok, binp or "nenalezen")
                except Exception as e:  # noqa: BLE001
                    add(f"engine {name}", False, f"{type(e).__name__}: {e}")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--expect")
    p.add_argument("--skip-engines", action="store_true")
    a = p.parse_args(argv)
    try:
        rep = run(Path(a.data), a.expect, a.skip_engines)
    except Exception as e:  # noqa: BLE001
        rep = {"ok": False, "checks": [{"name": "samotest", "ok": False, "detail": f"{type(e).__name__}: {e}"}]}
    print(json.dumps(rep, ensure_ascii=False))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
