"""Náhled ze stránky videa (PLAN.md kap. 23, etapa 4): obecná heuristika pro weby, které yt-dlp animovanou miniaturu ani
storyboard nenabídne. Z HTML stránky videa se zkusí vytáhnout adresa krátkého náhledového klipu nebo animovaného obrázku.

Hledá se (od nejspolehlivějšího): atributy `data-preview`, `data-mediabook`, `data-webm`/`data-mp4`/`data-gif`… ; adresy souborů
s typickým slovem (preview, trailer, teaser, hover, animated…) kdekoli v HTML i ve vloženém JSONu; `<video>`/`<source>` jen
s takovým slovem v adrese (hlavní přehrávač je plné video, ne náhled); nakonec `og:video`. Jen veřejné adresy http(s) a jen
formáty GIF, WebP, MP4 a WebM; stažení pak hlídá limit velikosti a kontrola obsahu (`catalogdetails.download_anim`).
"""
from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlsplit

from . import netsafe

EXT_RANK = {".mp4": 0, ".webm": 0, ".webp": 1, ".gif": 2}               # nejmenší formát má přednost
KEYWORDS = ("preview", "trailer", "teaser", "hover", "animated", "anim_", "mediabook", "thumbvid", "clip")
DATA_ATTRS = ("data-preview", "data-previewvideo", "data-video-preview", "data-preview-url", "data-preview-src", "data-mediabook", "data-mediabook-url",
              "data-webm", "data-mp4", "data-gif", "data-thumb-video", "data-hover", "data-animated", "data-animation")
_ATTR_RE = re.compile(r"""(?P<name>[\w:-]+)\s*=\s*(?P<q>["'])(?P<val>.*?)(?P=q)""", re.S)
_TAG_RE = re.compile(r"<(?P<tag>video|source|meta|img|a|div|li|span|article|link)\b(?P<attrs>[^>]{0,4000})>", re.I)          # omezené: bez kvadratického průchodu
_URL_RE = re.compile(r"""(?:https?:)?(?:\\?/){2}[^\s"'<>\\/]{1,200}(?:\\?/[^\s"'<>\\/]{0,200}){0,30}?\.(?:mp4|webm|gif|webp)(?:\?[^\s"'<>\\]{0,300})?""", re.I)
MAX_TEXT = 1_500_000                                                                                              # delší stránka se zkrátí


def is_public_url(url: str) -> bool:
    """Bez DNS: viz `netsafe.literal_ok` (skutečné ověření adresy a přesměrování dělá až stahování)."""
    return netsafe.literal_ok(url)


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


ID_KEYS = {"v", "id", "vid", "viewkey", "video", "videoid", "vkey", "key", "clip", "watch"}


def _id_tokens(page_url: str) -> list[str]:
    """Identifikátory videa z adresy stránky: části cesty a hodnoty typických parametrů (`viewkey`, `v`, `id`…) s číslicí, aspoň 5 znaků."""
    try:
        u = urlsplit(page_url)
    except ValueError:
        return []
    parts = [p for p in u.path.split("/") if p]
    for pair in u.query.split("&"):
        k, _, v = pair.partition("=")
        if k.lower() in ID_KEYS and v:
            parts.append(v)
    return [t.lower() for t in parts if len(t) >= 5 and re.search(r"\d", t)]


def _has_id(url: str, tokens: list[str]) -> bool:
    low = url.lower()
    return any(re.search(rf"(?<![0-9a-z]){re.escape(t)}(?![0-9a-z])", low) for t in tokens)       # celé slovo, ne podřetězec jiného id


def find_preview(text: str, page_url: str) -> str | None:
    """Adresa náhledového klipu nebo animace ze stránky videa, nebo None.

    Stránka videa obvykle obsahuje i doporučená videa s vlastními náhledy, proto se klip přijme jen tehdy, když je jednoznačný
    (mezi nejlepšími kandidáty je jediná adresa) nebo když obsahuje identifikátor tohoto videa z adresy stránky. Jinak by se
    ke videu přiřadila animace jiného videa; raději zůstane statická miniatura."""
    cands = _collect(text, page_url)
    if not cands:
        return None
    ids = _id_tokens(page_url)
    if ids:                                                               # klip s identifikátorem tohoto videa má přednost
        own = [c for c in cands if _has_id(c[3], ids)]
        if own:
            best_rank = min(c[0] for c in own)
            urls = {c[3] for c in own if c[0] == best_rank}
            return min(c for c in own if c[0] == best_rank)[3] if len(urls) == 1 else None
    top_rank = min(c[0] for c in cands)
    top = {c[3] for c in cands if c[0] == top_rank}
    if len(top) == 1:
        return next(iter(top))
    return None                                                           # víc různých kandidátů a žádný nepatří prokazatelně k tomuto videu


def _collect(text: str, page_url: str) -> list[tuple[int, int, int, str]]:
    """Všichni kandidáti na náhled ve stránce: (pořadí zdroje, pořadí formátu, pozice, adresa)."""
    text = text[:MAX_TEXT]
    cands: list[tuple[int, int, int, str]] = []

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
    return cands


# --- stránka zdroje (výpis videí): animace všech videí najednou ------------------------------------------
_TOK_RE = re.compile(r"[0-9a-z]{6,}")
LISTING_MAX_RANK = 2                                                      # na výpisu nepoužít og:video (to je hlavní video stránky, ne náhled)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOK_RE.findall(text.lower()) if re.search(r"\d", t)}


def url_tokens(url: str | None) -> set[str]:
    """Identifikátory z adresy: slova z cesty a hodnoty typických parametrů (aspoň 6 znaků, s číslicí)."""
    if not url:
        return set()
    try:
        u = urlsplit(url)
    except ValueError:
        return set()
    out = _tokens(u.path)
    for pair in u.query.split("&"):
        k, _, v = pair.partition("=")
        if k.lower() in ID_KEYS:
            out |= _tokens(v)
    return out


def _nokey(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0]


_A_RE = re.compile(r"<a\b(?P<attrs>[^>]{0,4000})>", re.I)


def _norm_page_url(u: str) -> tuple[str, str, str]:
    """Adresa stránky bez schématu, fragmentu a koncového lomítka: (hostitel, cesta, dotaz)."""
    try:
        sp = urlsplit(u)
    except ValueError:
        return ("", "", "")
    return (sp.netloc.lower(), sp.path.rstrip("/"), sp.query)


ANCHOR_MAX = 2500                                                         # klip a odkaz na video jedné karty jsou od sebe nejvýš tolik znaků


def _anchor_matches(text: str, page_url: str, items: list[dict], cands: list[tuple[int, int, int, str]]) -> tuple[dict[int, tuple], set[int]]:
    """Strukturální párování: klip patří videu, na jehož stránku vede odkaz `<a href>`, který klip obklopuje (klip je v téže značce
    nebo uvnitř odkazu, před jeho uzavřením). Spolehlivější než číslo v adrese, funguje i když web používá jiné identifikátory v adrese
    klipu a stránky. Vrací ({id položky: nejlepší klip}, {id položek, jejichž odkaz na stránce je})."""
    by_url = {}
    for it in items:
        k = _norm_page_url(it.get("url") or "")
        if k[0]:
            by_url.setdefault(k, []).append(it["id"])
    anchors: list[tuple[int, int]] = []                                    # (pozice značky <a>, id videa)
    seen: set[int] = set()
    for m in _A_RE.finditer(text[:MAX_TEXT]):
        href = next((a["val"] for a in _ATTR_RE.finditer(m.group("attrs")) if a["name"].lower() == "href"), None)
        if not href:
            continue
        ids = by_url.get(_norm_page_url(urljoin(page_url, html.unescape(href))))
        if ids and len(ids) == 1:                                           # adresa patřící jedinému videu
            anchors.append((m.start(), ids[0]))
            seen.add(ids[0])
    if not anchors:
        return {}, seen
    import bisect
    starts = [a[0] for a in anchors]
    best: dict[int, tuple[int, int, int, str]] = {}
    for c in cands:
        i = bisect.bisect_right(starts, c[2]) - 1
        if i < 0:
            continue
        pos, iid = anchors[i]
        if c[2] - pos > ANCHOR_MAX or "</a" in text[pos:c[2]].lower():     # odkaz už skončil: klip patří jinému místu stránky
            continue
        if iid not in best or c < best[iid]:
            best[iid] = c
    return best, seen


def match_listing(text: str, page_url: str, items: list[dict], context: list[dict] | None = None) -> tuple[dict[int, str], set[int], int]:
    """Na stránce zdroje (výpisu) spáruje náhledové klipy s videi podle společného identifikátoru: číslo nebo slovo z adresy klipu,
    které je i v adrese miniatury nebo stránky videa a identifikuje právě jedno video (a právě jeden klip). Nejednoznačné se
    nepřiřadí. `context` jsou další videa téhož zdroje (už vyřízená): počítají se do jedinečnosti identifikátorů (společné datum nesmí
    „zjedinečnět“ jen proto, že zbylo poslední nevyřízené video z toho měsíce), ale klip se jim nepřiřazuje. Vrací
    ({id položky: adresa klipu}, {id položek, které na stránce jsou}, počet nalezených klipů)."""
    cands = [c for c in _collect(text, page_url) if c[0] <= LISTING_MAX_RANK]
    if not cands:
        return {}, set(), 0
    by_tok: dict[str, list[tuple[int, int, int, str]]] = {}
    for c in cands:
        for t in url_tokens(c[3]):
            by_tok.setdefault(t, []).append(c)
    tok_items: dict[str, int] = {}
    toks = {it["id"]: url_tokens(it.get("thumb_url")) | url_tokens(it.get("url")) for it in items}
    for it in context or []:
        if it["id"] not in toks:
            toks_ctx = url_tokens(it.get("thumb_url")) | url_tokens(it.get("url"))
            for t in toks_ctx:
                tok_items[t] = tok_items.get(t, 0) + 1
    for ts in toks.values():
        for t in ts:
            tok_items[t] = tok_items.get(t, 0) + 1
    page_tokens = _tokens(text[:MAX_TEXT])
    found: dict[int, str] = {}
    by_anchor, seen = _anchor_matches(text, page_url, items, cands)
    for iid, c in by_anchor.items():
        found[iid] = c[3]
    for it in items:
        if it["id"] in by_anchor:
            continue
        mine = {t for t in toks[it["id"]] if tok_items[t] == 1}               # jen identifikátory patřící jedinému videu
        if mine & page_tokens:
            seen.add(it["id"])
        keys: dict[str, tuple] = {}
        for t in mine:
            group = by_tok.get(t)
            if not group:
                continue
            best = min(group)[:2]
            top = {_nokey(c[3]) for c in group if c[:2] == best}
            if len(top) == 1:                                                  # víc formátů téhož klipu: vybere se nejmenší
                c = min(group)
                keys[_nokey(c[3])] = c
            else:
                keys["?" + t] = ()                                             # nejednoznačné: tento identifikátor nerozhoduje, ale přiřazení znemožní
        if len(keys) == 1 and not next(iter(keys)).startswith("?"):
            found[it["id"]] = next(iter(keys.values()))[3]
    claimed: dict[str, list[int]] = {}
    for iid, u in found.items():
        claimed.setdefault(_nokey(u), []).append(iid)
    for ids in claimed.values():                                              # jeden klip pro víc videí: nepřiřadit nikomu
        if len(ids) > 1:
            for iid in ids:
                del found[iid]
    return found, seen, len(cands)


_NEXT_RE = re.compile(r"""<(?:a|link)\b[^>]{0,500}?\brel\s*=\s*["']?next["']?[^>]{0,500}?>""", re.I)
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.I)


def next_page_url(text: str, page_url: str, page_no: int) -> str | None:
    """Adresa další stránky výpisu: odkaz `rel="next"`, jinak ze stejné adresy s `page=<další číslo>`, když ho stránka nabízí."""
    text = text[:MAX_TEXT]
    m = _NEXT_RE.search(text)
    if m:
        h = _HREF_RE.search(m.group(0))
        if h:
            u = urljoin(page_url, html.unescape(h.group(1)))
            if u != page_url and netsafe.literal_ok(u):
                return u
    nxt = page_no + 1
    if re.search(rf"""[?&;]page={nxt}(?![0-9])""", text):
        sp = urlsplit(page_url)
        q = [kv for kv in sp.query.split("&") if kv and not kv.lower().startswith("page=")] + [f"page={nxt}"]
        u = sp._replace(query="&".join(q), fragment="").geturl()
        return u if netsafe.literal_ok(u) else None
    return None
