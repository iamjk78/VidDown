#!/usr/bin/env python3
"""Ostrá zkouška časového rozvrhu v Dockeru (PLAN.md kap. 21, etapa 3).

V jednorázovém kontejneru (oddělená data, bez Telegramu, vlastní port, TZ=Europe/Prague) ověří:
  A) zavřené okno: stav rozvrhu, čas dalšího otevření v místním čase kontejneru,
  B) zavřené okno drží ručně přidané stahování ve frontě, ale ručně přidaný zdroj katalogu se zjistí,
  C) dočasná výjimka stahování uvolní a jde zrušit,
  D) okno kolem „teď“ (včetně okna přes půlnoc) je otevřené a ukazuje čas zavření.

Použití (z kořene repozitáře, po `docker compose build`):  .venv/bin/python scripts/e2e_schedule.py
Nesahá na běžící VidDown ani na jeho data. Trvá asi minutu.
"""
from __future__ import annotations

import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
IMAGE, NAME, PORT = "viddown:latest", "viddown-e2e-sched", 8767
TZ = ZoneInfo("Europe/Prague")
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


def api(path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def wait(cond, timeout: float, what: str, poll: float = 1.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = cond()
        except (urllib.error.URLError, ConnectionError, OSError, ValueError, KeyError, IndexError):
            v = None
        if v:
            return v
        time.sleep(poll)
    raise SystemExit(f"Vypršel čas: {what}\n--- log kontejneru:\n{docker('logs', '--tail', '40', NAME)}")


def put_rules(rules: list, **extra) -> dict:
    return api("/api/settings", "PUT", {"schedule_enabled": True, "schedule_scope": ["queue", "catalog"], "schedule_rules": rules, **extra})


def job() -> dict:
    q = api("/api/state")["queue"]
    if q:
        return q[0]
    h = api("/api/history")
    h = h.get("items", h) if isinstance(h, dict) else h
    return h[0] if h else {"status": "(žádné)"}


class _Media(http.server.BaseHTTPRequestHandler):
    """Falešný web: x.mp4 je soubor s typem video/mp4 (yt-dlp ho vezme jako přímé video, takže zjištění projde bez sítě ven)."""
    def _head(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", "300000")
        self.end_headers()

    def do_HEAD(self):
        self._head()

    def do_GET(self):
        self._head()
        try:
            self.wfile.write(b"\0" * 300000)
        except OSError:
            pass

    def log_message(self, *a):
        pass


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="vd-e2e-sched-"))
    data = work / "data"
    data.mkdir()
    web = http.server.ThreadingHTTPServer(("0.0.0.0", 0), _Media)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    media = f"http://host.docker.internal:{web.server_address[1]}/x.mp4"
    try:
        shutil.copytree(ROOT / "data" / "engines", data / "engines", symlinks=True)
        (data / "settings.json").write_text(json.dumps({"engine_auto_update": False}), "utf-8")
        docker("rm", "-f", NAME)
        docker("run", "-d", "--name", NAME, "-p", f"127.0.0.1:{PORT}:8765", "-e", "VIDDOWN_ALLOW_NO_PASSWORD=1",
               "-e", "TZ=Europe/Prague", "-e", "PUID=501", "-e", "PGID=20", "-v", f"{data}:/data", IMAGE)
        wait(lambda: api("/api/state"), 60, "kontejner nenaběhl")
        now = datetime.now(TZ)

        say("A) zavřené okno")
        tomorrow = now + timedelta(days=1)
        r = put_rules([{"days": [tomorrow.weekday()], "windows": [["10:00", "11:00"]]}])
        s = api("/api/schedule")
        want = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 10, 0, tzinfo=TZ).timestamp()
        check(s["enabled"] and not s["open"] and not s["allowed"]["queue"] and not s["allowed"]["catalog"], "rozvrh je zavřený pro frontu i katalog")
        check(s["allowed"]["subscriptions"], "odběry mimo rozsah rozvrhu smějí")
        check(abs((s["next_open"] or 0) - want) < 1, "další otevření je zítra v 10:00 místního času kontejneru")
        check(api("/api/state")["in_window"] is False, "stav fronty hlásí mimo okno")

        say("B) zavřené okno: fronta stojí, ručně přidaný zdroj katalogu se zjistí")
        api("/api/jobs", "POST", {"urls": [media]})
        wait(lambda: job()["status"] in ("queued", "failed", "running"), 60, "zjištění stahování")
        api("/api/catalog/sources", "POST", {"urls": ["http://127.0.0.1:9/seznam"]})
        wait(lambda: api("/api/catalog")["sources"][0]["status"] in ("error", "done"), 90, "ručně přidaný zdroj se nezjistil")
        check(True, "ruční zdroj katalogu se zjistil i mimo okno")
        time.sleep(8)
        check(job()["status"] in ("new", "queued"), f"stahování čeká ve frontě (stav {job()['status']}, {job().get('error')})")

        say("C) dočasná výjimka")
        api("/api/schedule/override", "POST", {"hours": 1})
        check(api("/api/schedule")["allowed"]["queue"] and api("/api/schedule")["override_until"], "výjimka uvolní frontu")
        wait(lambda: job()["status"] not in ("new", "queued"), 90, "stahování po výjimce nezačalo")
        check(True, f"stahování se rozběhlo (stav {job()['status']})")
        api("/api/schedule/override", "DELETE")
        s = api("/api/schedule")
        check(not s["override_until"] and not s["allowed"]["queue"], "zrušená výjimka znovu zavře rozvrh")

        say("D) okno kolem „teď“ (i přes půlnoc)")
        now = datetime.now(TZ)
        start, end = now - timedelta(hours=1), now + timedelta(hours=1)
        put_rules([{"days": list(range(7)), "windows": [[start.strftime("%H:%M"), end.strftime("%H:%M")]]}])
        s = api("/api/schedule")
        check(s["open"] and s["allowed"]["queue"], "okno kolem teď je otevřené")
        check(abs((s["closes"] or 0) - end.replace(second=0, microsecond=0).timestamp()) < 1, "zavírá se za hodinu (místní čas)")
    finally:
        web.shutdown()
        docker("rm", "-f", NAME)
        shutil.rmtree(work, ignore_errors=True)
    say("\n" + ("VŠE PROŠLO" if not FAILED else f"SELHALO: {len(FAILED)}\n  - " + "\n  - ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
