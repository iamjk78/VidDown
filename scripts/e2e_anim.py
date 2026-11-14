#!/usr/bin/env python3
"""Ostrá zkouška animovaných náhledů katalogu v Dockeru (PLAN.md kap. 23, etapa 5).

V jednorázovém kontejneru (oddělená data, bez Telegramu, port 8768) proti falešnému webu na tomto počítači ověří celou cestu
zdroj „Stránka“ → seznam → podrobnosti (yt-dlp) → hledání náhledu na stránce videa (jen klip s identifikátorem tohoto videa,
doporučená videa se nepřiřadí) → stažení animace s limitem → filtr, služba souboru, místo na disku, smazání a Doplnit animace.

Použití (z kořene repozitáře, po `docker compose build`):  .venv/bin/python scripts/e2e_anim.py
Nesahá na běžící VidDown ani na jeho data. Trvá asi 1–2 minuty.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE, NAME, PORT = "viddown:latest", "viddown-e2e-anim", 8768
FAILED: list[str] = []
IDS = ["v1a2b3c", "v4d5e6f", "v7g8h9i"]            # třetí video nemá vlastní náhled, jen doporučená
GIF = b"GIF89a" + b"\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


def say(msg: str) -> None:
    print(msg, flush=True)


def check(cond: bool, msg: str) -> None:
    say(f"  {'OK   ' if cond else 'CHYBA'} {msg}")
    if not cond:
        FAILED.append(msg)


def docker(*args: str, timeout: int = 120) -> str:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def api(path: str, method: str = "GET", body: dict | None = None, raw: bool = False):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return (r.headers.get("content-type"), r.read()) if raw else json.loads(r.read() or b"{}")


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


class Web(http.server.BaseHTTPRequestHandler):
    base = ""

    def _send(self, body: bytes, ctype: str, head: bool = False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _serve(self, head: bool):
        p = self.path.split("?")[0]
        b = self.base
        if p == "/list":
            links = "".join(f'<a href="/v/{i}">Díl {i} 8.11.2026</a>' for i in IDS)
            return self._send(f"<html><head><title>Zkušební pořad</title></head><body>{links}</body></html>".encode(), "text/html; charset=utf-8", head)
        if p.startswith("/v/"):
            vid = p[3:]
            related = "".join(f'<li data-preview="{b}/prev/{o}x.gif"></li>' for o in IDS if o != vid)
            own = f'<div data-preview="{b}/prev/{vid}.gif"></div>' if vid != IDS[2] else ""
            page = (f'<html><head><title>{vid}</title></head><body><video controls><source src="{b}/media/{vid}.mp4" type="video/mp4"></video>'
                    f"{own}<ul>{related}</ul></body></html>")
            return self._send(page.encode(), "text/html; charset=utf-8", head)
        if p.startswith("/media/"):
            return self._send(b"\x00\x00\x00\x18ftypisom" + b"\0" * 2000, "video/mp4", head)
        if p.startswith("/prev/"):
            return self._send(GIF, "image/gif", head)
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)

    def log_message(self, *a):
        pass


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="vd-e2e-anim-"))
    data = work / "data"
    data.mkdir()
    web = http.server.ThreadingHTTPServer(("0.0.0.0", 0), Web)
    Web.base = f"http://fakeweb.test:{web.server_address[1]}"      # přes --add-host; ochrana náhledů jinak odmítá místní adresy, proto VIDDOWN_ALLOW_PRIVATE_PREVIEW=1
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        shutil.copytree(ROOT / "data" / "engines", data / "engines", symlinks=True)
        (data / "settings.json").write_text(json.dumps({"engine_auto_update": False, "catalog_gap": 0, "catalog_slow_browser": False,
                                                        "catalog_anim": True, "catalog_anim_pages": True, "catalog_anim_max_mb": 5}), "utf-8")
        docker("rm", "-f", NAME)
        docker("run", "-d", "--name", NAME, "-p", f"127.0.0.1:{PORT}:8765", "-e", "VIDDOWN_ALLOW_NO_PASSWORD=1", "-e", "TZ=Europe/Prague",
               "--add-host", "fakeweb.test:host-gateway", "-e", "VIDDOWN_ALLOW_PRIVATE_PREVIEW=1", "-e", "PUID=501", "-e", "PGID=20", "-v", f"{data}:/data", IMAGE)
        wait(lambda: api("/api/state"), 60, "kontejner nenaběhl")
        items = lambda q="": api("/api/catalog/items" + q)["items"]  # noqa: E731

        say("A) zdroj Stránka a podrobnosti")
        api("/api/catalog/sources", "POST", {"urls": [f"{Web.base}/list"]})
        wait(lambda: api("/api/catalog")["sources"][0]["status"] == "done", 90, "zdroj se nezjistil")
        check(api("/api/catalog")["sources"][0]["kind"] == "page" and len(items()) == 3, "zdroj typu Stránka má 3 videa")
        wait(lambda: all(i["detail_state"] == "done" for i in items()), 120, "podrobnosti")
        check(True, "yt-dlp zjistil podrobnosti všech tří stránek videí")

        say("B) hledání náhledu na stránce videa a stažení animace")
        wait(lambda: len(items("?anim=yes")) == 2, 120, "animace se nestáhly")
        have = {i["title"]: i for i in items()}
        yes = items("?anim=yes")
        check(len(yes) == 2 and len(items("?anim=no")) == 1, "filtr: 2 videa s animací, 1 bez")
        check(all(i["anim_kind"] == "image" and i["anim"] for i in yes), "karty mají adresu animace a typ obrázek")
        no = items("?anim=no")[0]
        check(IDS[2] in no["url"], "video bez vlastního náhledu animaci nedostalo (doporučená videa se nepřiřadila)")
        ctype, body = api(yes[0]["anim"].split("?")[0], raw=True)
        check(ctype == "image/gif" and body.startswith(b"GIF89a"), "služba souboru vrací GIF")
        d = api("/api/catalog/disk")
        check(d["anims"]["count"] == 2 and d["anims"]["bytes"] > 0, f"místo na disku: {d['anims']['count']} animace, {d['anims']['bytes']} B")

        say("C) smazání a Doplnit animace")
        api("/api/settings", "PUT", {"catalog_anim": False})
        r = api("/api/catalog/anim/delete", "POST")
        check(r["files"] == 2 and r["disk"]["anims"]["count"] == 0 and len(items("?anim=yes")) == 0, "Smazat animace: soubory pryč, miniatury zůstaly")
        time.sleep(5)
        check(len(items("?anim=yes")) == 0, "při vypnutém stahování se animace znovu nestáhly")
        api("/api/settings", "PUT", {"catalog_anim": True})
        wait(lambda: len(items("?anim=yes")) == 2, 90, "po zapnutí se animace nestáhly znovu")
        check(True, "po zapnutí se animace stáhly znovu (adresy zůstaly)")
        wait(lambda: api("/api/catalog")["details"]["anim_scan"] == 0, 60, "hledání na stránkách neskončilo")     # i třetí video musí být prohledané
        rf = api("/api/catalog/anim/refill", "POST")
        check(rf["pages"] == 1, f"Doplnit animace zopakuje hledání na stránce u 1 videa bez animace (pages={rf['pages']})")
    finally:
        web.shutdown()
        docker("rm", "-f", NAME)
        shutil.rmtree(work, ignore_errors=True)
    say("\n" + ("VŠE PROŠLO" if not FAILED else f"SELHALO: {len(FAILED)}\n  - " + "\n  - ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
