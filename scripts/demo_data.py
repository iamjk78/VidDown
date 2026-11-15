#!/usr/bin/env python3
"""Ukázková data pro snímky obrazovky v README: vymyšlená videa (adresy example.com), barevné zástupné miniatury, historie,
odběr a katalog. Nic se nestahuje a nic neodchází na internet.

    .venv/bin/python scripts/demo_data.py /tmp/vd-demo            # vytvoří data (složka se nejdřív vyprázdní)
    .venv/bin/python scripts/demo_data.py /tmp/vd-demo --serve    # ... a spustí jen GUI na http://127.0.0.1:8798/ (bez fronty,
                                                                   #     Telegramu a katalogu na pozadí – stav zůstane „zamrzlý“)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

PALETTE = [(91, 80, 214), (36, 150, 136), (214, 102, 60), (54, 120, 200), (176, 70, 140), (120, 150, 60), (200, 160, 40), (80, 90, 110)]

VIDEOS = [
    ("Výlet do hor – časosběr západu slunce", "Cestovatelský deník", 754, 2160, 1_900_000_000),
    ("Jak upéct kváskový chléb", "Kuchyně bez stresu", 1268, 1080, 640_000_000),
    ("Recenze: malý domácí NAS", "Technika v kostce", 913, 1440, 820_000_000),
    ("Koncert v parku (záznam)", "Městská scéna", 3621, 1080, 2_400_000_000),
    ("Jak opravit kolo za 10 minut", "Dílna", 602, 720, 210_000_000),
    ("Zahrada na jaře", "Zelené ruce", 845, 1080, 450_000_000),
]
DONE = [
    ("Mořské vlny – 1 hodina relaxace", "Klidné zvuky", 3600, 1080, 1_200_000_000, True),
    ("Kurz fotografie, díl 3", "Foto škola", 1520, 1080, 700_000_000, True),
    ("Starý film (restaurovaný)", "Filmový archiv", 5400, 720, 1_100_000_000, False),
]
VIDEOS_EN = [
    ("Mountain trip – sunset time-lapse", "Travel diary", 754, 2160, 1_900_000_000),
    ("How to bake sourdough bread", "Stress-free kitchen", 1268, 1080, 640_000_000),
    ("Review: a small home NAS", "Tech in a nutshell", 913, 1440, 820_000_000),
    ("Concert in the park (recording)", "City stage", 3621, 1080, 2_400_000_000),
    ("Fix a bike in 10 minutes", "Workshop", 602, 720, 210_000_000),
    ("The garden in spring", "Green fingers", 845, 1080, 450_000_000),
]
DONE_EN = [
    ("Ocean waves – 1 hour of relaxation", "Calm sounds", 3600, 1080, 1_200_000_000, True),
    ("Photography course, part 3", "Photo school", 1520, 1080, 700_000_000, True),
    ("Old film (restored)", "Film archive", 5400, 720, 1_100_000_000, False),
]
CATALOG_EN = [
    ("Morning run by the river", 642, 1080, 380_000_000), ("Weekend at the cottage", 1204, 2160, 1_600_000_000),
    ("Cooking soup", 733, 1080, 410_000_000), ("The city at night from a drone", 488, 2160, 980_000_000),
    ("Boat trip", 1830, 1080, 900_000_000), ("Autumn forest", 357, 1440, 300_000_000),
    ("Visiting the observatory", 2210, 1080, 1_050_000_000), ("Building a birdhouse", 905, 720, 260_000_000),
    ("Winter hike", 1499, 2160, 2_100_000_000), ("Still life with fruit", 214, 1080, 120_000_000),
    ("Market on the square", 1102, 1080, 600_000_000), ("Sunset by the sea", 420, 2160, 700_000_000),
]
CATALOG = [
    ("Ranní běh podél řeky", 642, 1080, 380_000_000), ("Víkend na chalupě", 1204, 2160, 1_600_000_000),
    ("Vaříme polévku", 733, 1080, 410_000_000), ("Noční město z dronu", 488, 2160, 980_000_000),
    ("Výlet lodí", 1830, 1080, 900_000_000), ("Podzimní les", 357, 1440, 300_000_000),
    ("Návštěva hvězdárny", 2210, 1080, 1_050_000_000), ("Stavba ptačí budky", 905, 720, 260_000_000),
    ("Zimní túra", 1499, 2160, 2_100_000_000), ("Zátiší s ovocem", 214, 1080, 120_000_000),
    ("Jarmark na náměstí", 1102, 1080, 600_000_000), ("Západ slunce u moře", 420, 2160, 700_000_000),
]


def png(path: Path, w: int, h: int, color: tuple[int, int, int], seed: int) -> None:
    """Zástupná miniatura: barevný přechod s bílým trojúhelníkem „přehrát“ (bez knihoven, čisté PNG)."""
    r0, g0, b0 = color
    rows = []
    cx, cy, s = w // 2, h // 2, min(w, h) // 6
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            t = (x + y + seed * 13) / (w + h)
            r, g, b = int(r0 * (1 - 0.45 * t)), int(g0 * (1 - 0.45 * t)), int(b0 * (1 - 0.45 * t))
            dx, dy = x - (cx - s // 2), y - cy
            if 0 <= dx <= s and abs(dy) <= (s - dx) * 0.58:                 # trojúhelník „přehrát“
                r = g = b = 245
            row += bytes((max(0, r), max(0, g), max(0, b)))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def build(data: Path, lang: str) -> None:
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)
    os.environ["VIDDOWN_DATA"] = str(data)
    en = lang == "en"
    videos, done, cat = (VIDEOS_EN, DONE_EN, CATALOG_EN) if en else (VIDEOS, DONE, CATALOG)
    from viddown import catalog
    from viddown.config import Settings
    from viddown.db import DB

    s = Settings(data / "settings.json")
    s.update({"download_dir": "/downloads", "language": lang, "theme": "light", "catalog_auto": False, "concurrency": 2, "queue_previews": False})
    db = DB(data / "viddown.db")
    db.kv_set("onboarded", True)
    now = time.time()
    thumbs = data / "thumbs"
    thumbs.mkdir()

    def job(title, channel, dur, height, size, **kw):
        jid = db.add(f"https://video.example/watch/{abs(hash(title)) % 10**8}", source="gui", kind="video", title=title, channel=channel,
                     duration=dur, height=height, size_est=size, thumb_url="https://img.example/demo.jpg", method="ytdlp", **kw)
        png(thumbs / f"{jid}.img", 320, 180, PALETTE[jid % len(PALETTE)], jid)
        return jid

    # právě se stahuje + čeká ve frontě
    first = job(*videos[0], status="running", started_at=now - 95)
    db.update(first, progress=0.42, downloaded=int(videos[0][4] * 0.42), total=videos[0][4], speed=18_500_000, eta=58, stage="download")
    for v in videos[1:]:
        job(*v, status="queued")
    # historie
    for i, (title, ch, dur, h, size, ok) in enumerate(done):
        jid = job(title, ch, dur, h, size, status="done" if ok else "failed", started_at=now - 7200 * (i + 1), finished_at=now - 7000 * (i + 1),
                  filepath=f"/downloads/{title}.mp4" if ok else None, filesize=size if ok else None,
                  error=None if ok else "ERROR: Video unavailable", error_kind=None if ok else "removed")
        db.record_download(db.get(jid), ok)
    # odběr
    db.sub_add("https://video.example/channel/travel-diary", "/downloads/" + videos[0][1], kind="channel",
               title=videos[0][1], last_check=now - 1800)
    # katalog
    catalog.add_sources(db, ["https://video.example/channel/vylety"])
    sid = db.query("select id from catalog_sources")[0]["id"]
    src_title = "Trips and nature" if en else "Výlety a příroda"
    entries = [{"key": f"demo {i}", "id": None, "url": f"https://video.example/watch/k{i}", "title": t, "channel": src_title,
                "duration": d, "thumb_url": f"https://img.example/k{i}.jpg", "thumb_alts": [], "height": h, "size": sz,
                "detail_state": "done", "published_at": now - 86400 * (i * 9 + 2)} for i, (t, d, h, sz) in enumerate(cat)]
    catalog.apply_listing(db, sid, {"kind": "channel", "title": src_title, "entries": entries, "complete": True}, "new", set(), set(), set())
    tdir = catalog.thumbs_dir(data, s)
    tdir.mkdir(parents=True, exist_ok=True)
    with db.conn() as c:
        for r in c.execute("select id from catalog_items").fetchall():
            png(tdir / f"{r['id']}.png", 320, 180, PALETTE[r["id"] % len(PALETTE)], r["id"])
            c.execute("update catalog_items set thumb_file=? where id=?", (f"{r['id']}.png", r["id"]))
        c.execute("update catalog_sources set last_scan=?", (now,))
    print(f"Ukázková data jsou v {data}")


def serve(data: Path, port: int) -> None:
    """Jen GUI nad ukázkovými daty: bez fronty, Telegramu a katalogu na pozadí (stav se nemění)."""
    os.environ["VIDDOWN_DATA"] = str(data)
    os.environ.setdefault("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    import uvicorn

    from viddown.daemon import AppState
    from viddown.server import create_app
    st = AppState()
    st.bot = None
    uvicorn.run(create_app(st), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("--lang", default="cs", choices=["cs", "en"])
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8798)
    a = ap.parse_args()
    build(a.data, a.lang)
    if a.serve:
        serve(a.data, a.port)
