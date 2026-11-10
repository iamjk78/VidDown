"""Pomocné funkce: názvy souborů, šablony, URL, chyby, formátování."""
from __future__ import annotations

import os
import re
import shutil
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.I)

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def extract_urls(text: str) -> list[str]:
    out = []
    for m in URL_RE.findall(text or ""):
        u = m.rstrip(".,;:!?)]}>")
        if u not in out:
            out.append(u)
    return out


def sanitize_filename(name: str, maxlen: int = 150) -> str:
    """Bezpečný název pro Windows, macOS i Linux. Diakritika zůstává."""
    name = unicodedata.normalize("NFC", str(name or ""))
    name = _FORBIDDEN.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".").strip()
    if not name:
        name = "video"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    if len(name.encode("utf-8")) > maxlen:
        b = name.encode("utf-8")[:maxlen]
        name = b.decode("utf-8", "ignore").rstrip(" .")
    return name


TOKENS = {
    # česky / anglicky -> klíč v info
    "název": "title", "title": "title",
    "kanál": "channel", "channel": "channel",
    "playlist": "playlist",
    "datum": "date", "date": "date",
    "rozlišení": "resolution", "resolution": "resolution",
    "id": "id",
    "pořadí": "index", "index": "index",
}


def render_template(template: str, info: dict) -> str:
    """Šablona názvu, např. "{kanál}_{název}". Prázdné tokeny se vypustí včetně oddělovače."""
    def val(key: str) -> str:
        k = TOKENS.get(key.lower(), key.lower())
        if k == "title":
            return str(info.get("title") or "")
        if k == "channel":
            return str(info.get("channel") or info.get("uploader") or "")
        if k == "playlist":
            return str(info.get("playlist_title") or "")
        if k == "date":
            d = str(info.get("upload_date") or "")
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
        if k == "resolution":
            h = info.get("height")
            return f"{h}p" if h else ""
        if k == "id":
            return str(info.get("id") or "")
        if k == "index":
            i = info.get("playlist_index")
            return f"{int(i):03d}" if i else ""
        return ""

    parts = [p for p in re.split(r"(\{[^{}]+\})", template or "{název}") if p]
    segs: list[tuple[str, str]] = []  # (typ, text): "v" = hodnota tokenu, "l" = doslovný text
    skip_next = False
    for p in parts:
        if p.startswith("{") and p.endswith("}"):
            v = val(p[1:-1])
            if v:
                segs.append(("v", v))
            elif segs and segs[-1][0] == "l":
                _, lit = segs.pop()  # prázdný token odstraní i oddělovač před sebou
                if re.search(r"[\[(]\s*$", lit):
                    skip_next = True  # … a u závorky i zavírací závorku za sebou
            else:
                skip_next = True    # prázdný token na začátku odstraní oddělovač za sebou
        else:
            if skip_next:
                skip_next = False
                continue
            segs.append(("l", p))
    out = "".join(t for _, t in segs)
    out = re.sub(r"\(\s*\)|\[\s*\]", "", out).strip(" _-–.,")
    if not out:
        out = str(info.get("title") or "video")
    return sanitize_filename(out)


def unique_target(directory: Path, stem: str, ext: str, companions=(".jpg",)) -> Path:
    """Najde volný název. Video i jeho miniatura dostanou stejnou příponu (2), (3)…"""
    n = 1
    while True:
        s = stem if n == 1 else f"{stem} ({n})"
        cand = directory / f"{s}{ext}"
        if not cand.exists() and not any((directory / f"{s}{c}").exists() for c in companions):
            return cand
        n += 1


def free_bytes(path: str | Path) -> int:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 0


def _mount_source(path: Path) -> str | None:
    """Zdroj připojení (sloupec 1 v /proc/mounts) pro nejdelší odpovídající přípojný bod. Jen Linux."""
    try:
        lines = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return None
    p = str(path.resolve())
    best, src = "", None
    for l in lines:
        parts = l.split()
        if len(parts) < 2:
            continue
        mp = parts[1].replace("\\040", " ")
        if (p == mp or p.startswith(mp.rstrip("/") + "/")) and len(mp) > len(best):
            best, src = mp, parts[0]
    return src


def free_space(path: str | Path) -> tuple[int | None, bool]:
    """Volné místo (bajty, spolehlivé?).

    Docker Desktop na macOS zpřístupňuje složky z /Volumes (síťová sdílení, externí disky) tak,
    že statvfs vrací volné místo interního disku Macu – takový údaj je nespolehlivý a vrací se None.
    """
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    src = _mount_source(p)
    if src and src.startswith("/run/host_mark/Volumes"):
        return None, False
    try:
        return shutil.disk_usage(p).free, True
    except OSError:
        return None, False


def fmt_bytes(n: float | None) -> str:
    if not n:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit not in ("B", "KB") else f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_duration(sec: float | None) -> str:
    if sec is None:
        return "—"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


YT_CHANNEL = re.compile(r"^https?://(www\.|m\.)?youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)(/[^?#]*)?", re.I)


def youtube_channel_base(url: str) -> str | None:
    """Vrátí základ URL kanálu YouTube, pokud URL míří na kanál bez konkrétního videa/playlistu."""
    m = YT_CHANNEL.match(url)
    if not m:
        return None
    tail = (m.group(3) or "").strip("/")
    if tail and tail.split("/")[0] not in ("", "videos", "shorts", "streams", "featured"):
        return None
    return f"https://www.youtube.com/{m.group(2)}"


def is_hls_response(url: str, content_type: str) -> bool:
    """Podle RFC 8216: HLS pozná MIME typ nebo přípona .m3u8/.m3u (inspirace hls-downloader)."""
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl"):
        return True
    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return False
    return path.endswith(".m3u8") or path.endswith(".m3u")


# ------------------------------------------------------------ chyby
ERROR_PATTERNS = [
    ("cookies", r"cookies database|could not (find|copy|open) .*cook|failed to decrypt|unsupported browser|cookie file .*(not found|invalid|does not exist)|invalid netscape format|does not look like a netscape"),
    ("unsupported", r"unsupported url|no video formats found|unable to extract|no media|not a valid url|is not a valid url|no suitable"),
    ("drm", r"drm|widevine|playready|fairplay"),
    ("login", r"sign in|log in|login|members?[- ]only|cookies|authentication|age[- ]restricted|confirm your age|private video"),
    ("geo", r"not available in your country|geo.?restrict|geoblock"),
    ("removed", r"video unavailable|has been removed|does not exist|404: not found|account.*terminated|video is no longer"),
    ("live", r"live event will begin|is live|premieres in"),
    ("network", r"too many requests|http error 429|timed out|timeout|connection|temporary failure|http error 5\d\d|reset by peer|network|name resolution|ssl"),
]


def classify_error(message: str) -> str:
    m = (message or "").lower()
    for kind, pat in ERROR_PATTERNS:
        if re.search(pat, m):
            return kind
    return "other"


def fallback_allowed(kind: str) -> bool:
    """Na další metodu se přechází jen když metoda video nenašla."""
    return kind in ("unsupported", "other")


def retry_allowed(kind: str) -> bool:
    return kind in ("network", "other")


def in_schedule(settings: dict, now: float | None = None) -> bool:
    if not settings.get("schedule_enabled"):
        return True
    t = time.localtime(now or time.time())
    days = settings.get("schedule_days") or []
    sh, sm = map(int, settings["schedule_start"].split(":"))
    eh, em = map(int, settings["schedule_end"].split(":"))
    cur = t.tm_hour * 60 + t.tm_min
    start, end = sh * 60 + sm, eh * 60 + em
    if start == end:
        return t.tm_wday in days
    if start < end:
        return t.tm_wday in days and start <= cur < end
    # okno přes půlnoc: den se počítá podle začátku okna
    if cur >= start:
        return t.tm_wday in days
    return ((t.tm_wday - 1) % 7) in days and cur < end


def in_docker() -> bool:
    return Path("/.dockerenv").exists() or os.environ.get("VIDDOWN_DOCKER") == "1"


def check_dir_writable(path: str, docker: bool | None = None) -> tuple[bool, str]:
    """Ověří, že do složky jde zapisovat (případně ji vytvoří). Vrací (ok, chybová zpráva).

    V Dockeru odmítne cestu mimo připojené svazky – zápis by skončil uvnitř kontejneru a soubory by se ztratily.
    """
    import uuid

    docker = in_docker() if docker is None else docker
    raw = (path or "").strip()
    if not raw:
        return False, "Zadejte cestu ke složce."
    p = Path(raw).expanduser()
    if not p.is_absolute():
        return False, f"Cesta „{raw}“ není absolutní. Zadejte celou cestu (např. /Volumes/NAS/Videa)."
    anc = p
    while not anc.exists() and anc != anc.parent:
        anc = anc.parent
    if docker:
        try:
            if os.stat(anc).st_dev == os.stat("/").st_dev:
                return False, (f"Složka „{p}“ neleží na svazku připojeném do kontejneru. "
                               "V docker-compose.yml ji připojte v sekci volumes (např. /downloads nebo /nas) a zadejte cestu uvnitř.")
        except OSError as e:
            return False, f"Složku „{p}“ nelze ověřit: {e.strerror or e}"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"Složku „{p}“ nelze vytvořit: {e.strerror or e}. Zadejte platnou cestu, kam má aplikace přístup."
    if not p.is_dir():
        return False, f"„{p}“ není složka."
    # zkouška zápisu složkou, ne souborem: SMB (macOS přes Docker) by po smazání otevřeného souboru nechal .smbdelete*
    test = p / f".viddown-test-{uuid.uuid4().hex[:8]}"
    try:
        test.mkdir()
        test.rmdir()
    except OSError as e:
        return False, f"Do složky „{p}“ nelze zapisovat: {e.strerror or e}. Zadejte platnou cestu, kam má aplikace přístup."
    return True, ""


def which(name: str) -> str | None:
    return shutil.which(name)


def is_frozen() -> bool:
    import sys
    return bool(getattr(sys, "frozen", False))


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")
