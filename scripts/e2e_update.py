#!/usr/bin/env python3
"""Ostrá zkouška aktualizací zevnitř v Dockeru (PLAN.md kap. 18, etapa 4).

V jednorázovém kontejneru (oddělená data, bez Telegramu a bez fronty, vlastní port) a proti falešnému GitHubu projde:
  A) úspěšnou aktualizaci: kontrola, stažení, samotest, restart kontejneru, nová verze běží a po 120 s je „zdravá“,
  B) vadnou verzi, která projde samotestem, ale při startu spadne: po dvou pádech se sama vrátí předchozí verze,
  C) vadnou verzi s migrací databáze a pádem: po návratu je databáze obnovená ze zálohy a data zůstala.

Použití (z kořene repozitáře, po `docker compose build`):  .venv/bin/python scripts/e2e_update.py
Nesahá na běžící VidDown ani na jeho data. Trvá asi 5–6 minut (zdravá doba nové verze je 120 s).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tests.test_appupdate_remote import REPO, TOKEN, Fake  # noqa: E402

IMAGE, NAME, PORT = "viddown:latest", "viddown-e2e", 8766
FAILED: list[str] = []


def say(msg: str) -> None:
    print(msg, flush=True)


def check(cond: bool, msg: str) -> None:
    say(f"  {'OK   ' if cond else 'CHYBA'} {msg}")
    if not cond:
        FAILED.append(msg)


def docker(*args: str, timeout: int = 120) -> str:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 120):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def try_api(path: str, **kw):
    try:
        return api(path, **kw)
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, ValueError):
        return None


def wait(cond, timeout: float, what: str, poll: float = 2.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = cond()
        except Exception:  # noqa: BLE001
            v = None
        if v:
            return v
        time.sleep(poll)
    raise SystemExit(f"Vypršel čas: {what}\n--- log kontejneru:\n{docker('logs', '--tail', '40', NAME)}")


def rewrite_zip(zp: Path, edits: dict[str, callable]) -> None:
    tmp = zp.with_suffix(".new")
    done = set()
    with zipfile.ZipFile(zp) as zi, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            data = zi.read(n)
            if n in edits:
                data = edits[n](data.decode("utf-8")).encode("utf-8")
                done.add(n)
            zo.writestr(n, data)
    assert done == set(edits), "úprava archivu se nepoužila"
    tmp.replace(zp)


CRASH_ANCHOR = "    import uvicorn\n\n    from .server import create_app"


def crash_on_start(text: str) -> str:
    assert CRASH_ANCHOR in text
    return text.replace(CRASH_ANCHOR, '    raise RuntimeError("e2e: pád při startu")\n' + CRASH_ANCHOR, 1)


def add_migration(text: str) -> str:
    return text + '\nMIGRATIONS.append((MIGRATIONS[-1][0] + 1, "alter table jobs add column zz_e2e text;"))\n'


def mutate_crash(zp: Path) -> None:
    rewrite_zip(zp, {"viddown/daemon.py": crash_on_start})


def mutate_migrate_and_crash(zp: Path) -> None:
    rewrite_zip(zp, {"viddown/daemon.py": crash_on_start, "viddown/db.py": add_migration})


def app_status() -> dict | None:
    return try_api("/api/app")


def release_and_restart(fake: Fake, work: Path, version: str, mutate=None) -> None:
    fake.publish(work, version, mutate=mutate)
    c = api("/api/app/check", "POST")
    check(c["check"]["status"] == "available" and c["check"]["version"] == version, f"kontrola najde verzi {version}")
    u = api("/api/app/update", "POST", {}, timeout=300)
    check(u["result"]["status"] == "activated" and u["status"]["prepared"], f"verze {version} stažena, otestována a připravena")
    api("/api/restart", "POST")
    time.sleep(3)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="vd-e2e-"))
    data = work / "data"
    data.mkdir()
    fake = Fake(bind="0.0.0.0", public="host.docker.internal")
    try:
        say(f"Příprava: {work}")
        shutil.copytree(ROOT / "data" / "engines", data / "engines", symlinks=True)   # kvůli samotestu (ffmpeg, yt-dlp)
        (data / "settings.json").write_text(json.dumps({"app_update_repo": REPO, "engine_auto_update": False}), "utf-8")
        docker("rm", "-f", NAME)
        out = docker("run", "-d", "--name", NAME, "--restart", "unless-stopped", "-p", f"127.0.0.1:{PORT}:8765",
                     "-e", "VIDDOWN_ALLOW_NO_PASSWORD=1", "-e", "PUID=501", "-e", "PGID=20",
                     "-e", f"VIDDOWN_GITHUB_API={fake.url}", "-e", f"VIDDOWN_APP_UPDATE_TOKEN={TOKEN}",
                     "-v", f"{data}:/data", IMAGE)
        say(f"Kontejner: {out[:12]}")
        st = wait(lambda: app_status(), 90, "kontejner nenaběhl")
        base = st["baseline"]
        check(st["running"] == base and st["current"] is None, f"start z obrazu ({base})")

        say("\nA) úspěšná aktualizace")
        release_and_restart(fake, work, "9.9.9")
        st = wait(lambda: (s := app_status()) and s["running"] == "9.9.9" and s, 120, "nová verze nenaběhla")
        check(st["current"] == "9.9.9" and st["probation"] and st["probation"]["attempts"] == 1, "po restartu běží 9.9.9 ve zkušební době")
        say("  čekám 120 s na zdravý stav…")
        st = wait(lambda: (s := app_status()) and s["probation"] is None and s, 180, "zkušební doba neskončila", poll=5)
        check(any(e["kind"] == "healthy" and e["version"] == "9.9.9" for e in st["events"]), "verze 9.9.9 je označena za zdravou")

        say("\nB) vadná verze spadne při startu")
        release_and_restart(fake, work, "9.9.10", mutate=mutate_crash)
        st = wait(lambda: (s := app_status()) and "9.9.10" in s["skipped"] and s, 180, "návrat nenastal")
        check(st["running"] == "9.9.9" and st["current"] == "9.9.9", "po dvou pádech se vrátila verze 9.9.9")
        check(any(e["kind"] == "rolled_back" and e["version"] == "9.9.10" for e in st["events"]), "událost o návratu je zapsaná")
        check(int(docker("inspect", "-f", "{{.RestartCount}}", NAME) or 0) >= 2, "kontejner se opakovaně restartoval")
        check(api("/api/app/check", "POST")["check"]["status"] == "skipped", "vadná verze se při další kontrole přeskakuje")

        say("\nC) vadná verze s migrací databáze")
        docker("exec", NAME, "python", "-c",
               "from viddown.db import DB; d=DB('/data/viddown.db'); d.add('https://example.com/e2e', status='done')")
        before = docker("exec", NAME, "python", "-c",
                        "import sqlite3;c=sqlite3.connect('/data/viddown.db');print(c.execute('select count(*) from jobs').fetchone()[0], c.execute('pragma user_version').fetchone()[0])").split()
        release_and_restart(fake, work, "9.9.11", mutate=mutate_migrate_and_crash)
        st = wait(lambda: (s := app_status()) and "9.9.11" in s["skipped"] and s, 180, "návrat po migraci nenastal")
        after = docker("exec", NAME, "python", "-c",
                       "import sqlite3;c=sqlite3.connect('/data/viddown.db');print(c.execute('select count(*) from jobs').fetchone()[0], c.execute('pragma user_version').fetchone()[0], c.execute('pragma integrity_check').fetchone()[0])").split()
        check(st["running"] == "9.9.9", "po návratu běží 9.9.9")
        check(after[:2] == before and after[2] == "ok", f"databáze obnovena ze zálohy (schéma {before[1]}, úlohy {before[0]}, kontrola ok)")
        failed = data / "viddown.db.failed-9.9.11"
        check(failed.exists(), "poškozená databáze zůstala vedle (viddown.db.failed-9.9.11)")
        check(any("databáze obnovena" in e["msg"] for e in st["events"] if e["kind"] == "rolled_back"), "událost zmiňuje obnovu databáze")
    finally:
        fake.close()
        say("\nÚklid…")
        docker("rm", "-f", NAME)
        shutil.rmtree(work, ignore_errors=True)
    say("\n" + ("VŠE V POŘÁDKU" if not FAILED else f"SELHALO ({len(FAILED)}): " + "; ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
