"""Miniatury: mezipaměť pro GUI a výsledný JPG vedle videa."""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

from . import netsafe

log = logging.getLogger("viddown.thumbs")
UA = "Mozilla/5.0 (VidDown)"


def cache_dir(data: Path) -> Path:
    p = data / "thumbs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cached(data: Path, jid: int) -> Path | None:
    for ext in (".jpg", ".img"):
        p = cache_dir(data) / f"{jid}{ext}"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")


def referer_of(page_url: str | None) -> str | None:
    """Adresa stránky videa jako Referer pro miniatury (mnoho CDN je bez něj odmítne): schéma a hostitel s lomítkem."""
    try:
        from urllib.parse import urlsplit
        u = urlsplit(page_url or "")
    except ValueError:
        return None
    return f"{u.scheme}://{u.netloc}/" if u.scheme in ("http", "https") and u.netloc else None


MAX_THUMB_BYTES = 15 * 1024 * 1024
PROXY: str | None = None          # proxy z nastavení (nastavuje server při startu a při změně nastavení) pro miniatury z fronty


def fetch(url: str, dest: Path, timeout=20, referer: str | None = None, proxy: str | None = None) -> bool:
    """Stáhne miniaturu (adresy pocházejí od cizích webů): jen veřejné adresy i po přesměrování, limit velikosti a celkového času."""
    headers = {"User-Agent": BROWSER_UA, "Referer": referer} if referer else {"User-Agent": UA}
    try:
        got = netsafe.fetch_limited(url, headers, MAX_THUMB_BYTES, PROXY if proxy is None else proxy, total_timeout=float(timeout))
        if got is None or got[0] != 200 or not got[2]:
            return False
        dest.write_bytes(got[2])
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("miniatura %s: %s", url, e)
        return False


def to_jpg(ffmpeg: str | None, src: Path, dest: Path) -> bool:
    """Převede obrázek (WebP, PNG…) na JPG v plném rozlišení."""
    if not ffmpeg:
        return False
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dest)],
                       capture_output=True, timeout=60, creationflags=flags)
    return r.returncode == 0 and dest.exists()


def frame_from_video(ffmpeg: str | None, video: Path, dest: Path) -> bool:
    if not ffmpeg:
        return False
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    for ss in ("3", "0"):
        r = subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", ss, "-i", str(video), "-frames:v", "1", "-q:v", "2", str(dest)],
                           capture_output=True, timeout=120, creationflags=flags)
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return True
    return False


def ensure_cached(data: Path, job: dict) -> Path | None:
    """Miniatura pro GUI: z mezipaměti, z hotového JPG vedle videa nebo stažená z thumb_url."""
    jid = job["id"]
    c = cached(data, jid)
    if c:
        return c
    if job.get("filepath"):
        side = Path(job["filepath"]).with_suffix(".jpg")
        if side.exists():
            return side
    url = job.get("thumb_url")
    if url and url.startswith("http"):
        dest = cache_dir(data) / f"{jid}.img"
        if fetch(url, dest):
            return dest
    return None


def drop(data: Path, jid: int) -> None:
    for ext in (".jpg", ".img"):
        (cache_dir(data) / f"{jid}{ext}").unlink(missing_ok=True)


def final_jpg(data: Path, job: dict, video: Path, staged_thumb: Path | None, dest: Path, ffmpeg: str | None) -> bool:
    """Uloží JPG se stejným názvem jako video do cílové složky."""
    try:
        if staged_thumb and staged_thumb.exists():
            if staged_thumb.suffix.lower() in (".jpg", ".jpeg"):
                shutil.move(str(staged_thumb), dest)
                return True
            if to_jpg(ffmpeg, staged_thumb, dest):
                return True
        src = ensure_cached(data, job)
        if src and src.exists():
            if src.suffix == ".jpg" and src.read_bytes()[:3] == b"\xff\xd8\xff":
                shutil.copyfile(src, dest)
                return True
            if to_jpg(ffmpeg, src, dest):
                return True
        if job.get("thumb_url") and job["thumb_url"].startswith("http"):
            tmp = dest.with_suffix(".tmpimg")
            if fetch(job["thumb_url"], tmp):
                ok = to_jpg(ffmpeg, tmp, dest)
                tmp.unlink(missing_ok=True)
                if ok:
                    return True
        return frame_from_video(ffmpeg, video, dest)
    except Exception as e:  # noqa: BLE001
        log.warning("miniatura pro %s: %s", video, e)
        return False
