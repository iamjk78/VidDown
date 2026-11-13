"""Animovaný náhled z storyboardu (PLAN.md kap. 23, etapa 3).

yt-dlp u některých webů (YouTube a další) vypíše mezi formáty „storyboard“: seznam obrázků (sprite sheetů), z nichž každý
obsahuje mřížku `columns × rows` malých okének z videa. Z několika okének rovnoměrně z celého videa složí ffmpeg krátký
smyčkový MP4 bez zvuku. Specifikace se ukládá do `catalog_items.anim_url` jako `sb:<JSON>` (bez změny schématu).
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import uuid
from pathlib import Path

import httpx

from . import thumbs

log = logging.getLogger("viddown.storyboard")

PREFIX = "sb:"
MAX_SHEETS = 8              # nejvýš tolik obrázků se stáhne (rovnoměrně z celého videa)
MAX_SHEET_BYTES = 3 * 1024 * 1024
MAX_FRAMES = 24             # okének v animaci
FPS = 4                     # smyčka ~6 s
WIDTH = 320                 # šířka výsledného videa
PREFERRED_WIDTH = 320       # který storyboard se vybere (nejbližší této šířce okénka, 120–480)


def is_spec(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def candidate(info: dict) -> str | None:
    """Specifikace storyboardu z formátů yt-dlp (`sb:<JSON>`), nebo None. Vybere storyboard s okénkem nejblíž 320 px."""
    best, best_key = None, None
    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue
        if not (f.get("ext") == "mhtml" or "storyboard" in str(f.get("format_note") or "").lower() or str(f.get("format_id") or "").startswith("sb")):
            continue
        frags = [x for x in (f.get("fragments") or []) if isinstance(x, dict) and isinstance(x.get("url"), str) and x["url"].startswith("http")]
        try:
            cols, rows, w, h = int(f["columns"]), int(f["rows"]), int(f["width"]), int(f["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if not frags or not (1 <= cols <= 20 and 1 <= rows <= 20) or not 120 <= w <= 480 or h < 1:
            continue
        key = abs(w - PREFERRED_WIDTH)
        if best_key is None or key < best_key:
            best, best_key = (f, frags, cols, rows, w, h), key
    if best is None:
        return None
    f, frags, cols, rows, w, h = best
    fps = f.get("fps") or 0
    counts = []
    for x in frags:                                        # okének v obrázku: poslední bývá neúplný
        d = x.get("duration")
        n = round(float(d) * float(fps)) if d and fps else cols * rows
        counts.append(max(1, min(cols * rows, n)))
    keep = list(range(len(frags)))
    if len(keep) > MAX_SHEETS:                             # rovnoměrně z celého videa
        keep = sorted({round(i * (len(frags) - 1) / (MAX_SHEETS - 1)) for i in range(MAX_SHEETS)})
    spec = {"u": [frags[i]["url"] for i in keep], "n": [counts[i] for i in keep], "c": cols, "r": rows, "w": w, "h": h}
    return PREFIX + json.dumps(spec, separators=(",", ":"))


def parse(value: str) -> dict | None:
    try:
        spec = json.loads(value[len(PREFIX):])
        ok = (isinstance(spec, dict) and isinstance(spec["u"], list) and spec["u"] and len(spec["u"]) == len(spec["n"])
              and all(isinstance(u, str) and u.startswith("http") for u in spec["u"]) and all(isinstance(n, int) and n >= 1 for n in spec["n"])
              and all(isinstance(spec[k], int) and spec[k] >= 1 for k in ("c", "r", "w", "h")))
    except (ValueError, KeyError, TypeError):
        return None
    return spec if ok else None


def pick_frames(spec: dict, target: int = MAX_FRAMES) -> list[tuple[int, int, int]]:
    """Okénka rovnoměrně přes všechny stažené obrázky: seznam (obrázek, sloupec, řádek)."""
    cols = spec["c"]
    all_frames = [(s, i % cols, i // cols) for s, n in enumerate(spec["n"]) for i in range(n)]
    total = len(all_frames)
    if total <= target:
        return all_frames
    return [all_frames[j * total // target] for j in range(target)]


def _is_image(head: bytes) -> bool:
    return head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n" or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")


def _filter(spec: dict, frames: list[tuple[int, int, int]], used: list[int], width: int) -> str:
    w, h = spec["w"], spec["h"]
    parts, labels = [], []
    for k, (s, c, r) in enumerate(frames):
        parts.append(f"[{used.index(s)}:v]crop={w}:{h}:{c * w}:{r * h},scale={width}:-2,setsar=1,format=yuv420p[f{k}]")
        labels.append(f"[f{k}]")
    # okénka jsou jednosnímkové vstupy bez délky: po spojení se jim přidělí pravidelné časy (jinak by splynula)
    return ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(frames)}:v=1:a=0,setpts=N/({FPS}*TB)[v]"


def build(folder: Path, item_id: int, value: str, ffmpeg: str | None, max_bytes: int, referer: str | None = None) -> str | None:
    """Stáhne obrázky storyboardu a složí z nich `<id>.anim.mp4`. Vrací název souboru, nebo None (špatná specifikace, chybí
    ffmpeg, obrázek se nepodařilo stáhnout, výsledek nad limit)."""
    spec = parse(value)
    if spec is None or not ffmpeg:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    frames = pick_frames(spec)
    used = sorted({s for s, _, _ in frames})
    token = uuid.uuid4().hex[:8]
    sheets = {s: folder / f"{item_id}.sb{s}.{token}.part" for s in used}
    out = folder / f"{item_id}.anim.{token}.mp4.part"
    try:
        headers = {"User-Agent": thumbs.BROWSER_UA, "Referer": referer} if referer else {"User-Agent": thumbs.UA}
        with httpx.Client(follow_redirects=True, timeout=30, headers=headers) as c:
            for s in used:
                r = c.get(spec["u"][s])
                if r.status_code != 200 or not r.content or len(r.content) > MAX_SHEET_BYTES or not _is_image(r.content[:16]):
                    return None
                sheets[s].write_bytes(r.content)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        for crf, width in ((28, WIDTH), (36, 240)):                          # nad limit: druhý pokus s menším obrazem a vyšší kompresí
            cmd = [ffmpeg, "-y", "-v", "error"]
            for s in used:
                cmd += ["-framerate", str(FPS), "-i", str(sheets[s])]
            cmd += ["-filter_complex", _filter(spec, frames, used, width), "-map", "[v]", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", "-f", "mp4", str(out)]
            r = subprocess.run(cmd, capture_output=True, timeout=120, creationflags=flags)
            if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
                log.debug("storyboard ffmpeg: %s", r.stderr.decode("utf-8", "replace")[-300:])
                return None
            if out.stat().st_size <= max_bytes:
                final = folder / f"{item_id}.anim.mp4"
                out.replace(final)
                for other in ("webm", "gif", "webp"):
                    (folder / f"{item_id}.anim.{other}").unlink(missing_ok=True)
                return final.name
        return None
    except (OSError, subprocess.SubprocessError, httpx.HTTPError) as e:
        log.debug("storyboard %s: %s", item_id, e)
        return None
    finally:
        for p in (*sheets.values(), out):
            p.unlink(missing_ok=True)
