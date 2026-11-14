"""Náhled ze stránky videa (PLAN.md kap. 23, etapa 4): obecná heuristika pro weby, které yt-dlp animovanou miniaturu ani
storyboard nenabídne. Z HTML stránky videa se zkusí vytáhnout adresa krátkého náhledového klipu nebo animovaného obrázku.

Hledá se (od nejspolehlivějšího): atributy `data-preview`, `data-mediabook`, `data-webm`/`data-mp4`/`data-gif`… ; adresy souborů
s typickým slovem (preview, trailer, teaser, hover, animated…) kdekoli v HTML i ve vloženém JSONu; `<video>`/`<source>` jen
s takovým slovem v adrese (hlavní přehrávač je plné video, ne náhled); nakonec `og:video`. Jen veřejné adresy http(s) a jen
formáty GIF, WebP, MP4 a WebM; stažení pak hlídá limit velikosti a kontrola obsahu (`catalogdetails.download_anim`).
"""
from __future__ import annotations

import html
import ipaddress
import re
from urllib.parse import urljoin, urlsplit

EXT_RANK = {".mp4": 0, ".webm": 0, ".webp": 1, ".gif": 2}               # nejmenší formát má přednost
KEYWORDS = ("preview", "trailer", "teaser", "hover", "animated", "anim_", "mediabook", "thumbvid", "clip")
DATA_ATTRS = ("data-preview", "data-previewvideo", "data-video-preview", "data-preview-url", "data-preview-src", "data-mediabook", "data-mediabook-url",
              "data-webm", "data-mp4", "data-gif", "data-thumb-video", "data-hover", "data-animated", "data-animation")
_ATTR_RE = re.compile(r"""(?P<name>[\w:-]+)\s*=\s*(?P<q>["'])(?P<val>.*?)(?P=q)""", re.S)
_TAG_RE = re.compile(r"<(?P<tag>video|source|meta|img|a|div|li|span|article|link)\b(?P<attrs>[^>]*)>", re.I | re.S)
_URL_RE = re.compile(r"""(?:https?:)?(?:\\?/){2}[^\s"'<>\\]+?(?:\\/[^\s"'<>\\]+?)*\.(?:mp4|webm|gif|webp)(?:\?[^\s"'<>\\]*)?""", re.I)


def is_public_url(url: str) -> bool:
    """Jen http(s) na veřejného hostitele: žádná místní adresa (localhost, .local, privátní IP)."""
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not host or host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan")):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _ext(url: str) -> str:
    path = urlsplit(url).path.lower()
    for e in EXT_RANK:
        if path.endswith(e):
            return e
    return ""


def _clean(raw: str, page_url: str) -> str | None:
    u = html.unescape(raw.strip().replace("\\/", "/"))
    if not u or u.startswith(("data:", "blob:", "javascript:")):
        return None
    u = urljoin(page_url, u)
    return u if _ext(u) and is_public_url(u) else None


def _has_keyword(url: str) -> bool:
    low = url.lower()
    return any(k in low for k in KEYWORDS)


def _id_tokens(page_url: str) -> list[str]:
    """Identifikátory videa z adresy stránky (hodnoty parametrů a části cesty s číslicí, aspoň 5 znaků), např. `viewkey=ab12cd34`."""
    try:
        u = urlsplit(page_url)
    except ValueError:
        return []
    parts = [p for p in u.path.split("/") if p] + [v for pair in u.query.split("&") for v in pair.split("=")[1:]]
    return [t.lower() for t in parts if len(t) >= 5 and re.search(r"\d", t)]


def find_preview(text: str, page_url: str) -> str | None:
    """Adresa náhledového klipu nebo animace ze stránky videa, nebo None.

    Stránka videa obvykle obsahuje i doporučená videa s vlastními náhledy, proto se klip přijme jen tehdy, když je jednoznačný
    (mezi nejlepšími kandidáty je jediná adresa) nebo když obsahuje identifikátor tohoto videa z adresy stránky. Jinak by se
    ke videu přiřadila animace jiného videa; raději zůstane statická miniatura."""
    cands: list[tuple[int, int, int, str]] = []                          # (pořadí zdroje, pořadí formátu, pozice, adresa)

    def add(rank: int, raw: str, pos: int) -> None:
        u = _clean(raw, page_url)
        if u:
            cands.append((rank, EXT_RANK[_ext(u)], pos, u))

    for m in _TAG_RE.finditer(text):
        tag, attrs = m.group("tag").lower(), {a["name"].lower(): a["val"] for a in _ATTR_RE.finditer(m.group("attrs"))}
        for name in DATA_ATTRS:
            if attrs.get(name):
                add(0, attrs[name], m.start())
        if tag == "meta" and (attrs.get("property") or attrs.get("name") or "").lower() in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"):
            add(3, attrs.get("content", ""), m.start())
        elif tag in ("video", "source"):
            for k in ("src", "data-src"):
                if attrs.get(k) and _has_keyword(attrs[k]):
                    add(2, attrs[k], m.start())
        elif tag == "img":
            for k in ("src", "data-src", "data-original"):
                v = attrs.get(k, "")
                if v and _ext(v) in (".gif", ".webp") and _has_keyword(v):
                    add(1, v, m.start())
    for m in _URL_RE.finditer(text):                                      # i ve vloženém JSONu a skriptech
        raw = m.group(0)
        if _has_keyword(raw):
            add(1, raw, m.start())
    if not cands:
        return None
    ids = _id_tokens(page_url)
    if ids:                                                               # klip s identifikátorem tohoto videa má přednost
        own = [c for c in cands if any(t in c[3].lower() for t in ids)]
        if own:
            return min(own)[3]
    top_rank = min(c[0] for c in cands)
    top = {c[3] for c in cands if c[0] == top_rank}
    if len(top) == 1:
        return next(iter(top))
    return None                                                           # víc různých kandidátů a žádný nepatří prokazatelně k tomuto videu
