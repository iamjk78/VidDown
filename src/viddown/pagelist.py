"""Odběr ze „stránky s videi“: web bez kanálu/playlistu, kde je seznam dílů (s podstránkami) a každý díl má vlastní stránku.

Postup:
1. ze seznamu najdeme odkazy na díly (opakující se vzor adresy, např. `…?id=28&pg=0&video=10139`) a jejich názvy,
2. datum dílu vezmeme z názvu odkazu (8.11.2026, 2026-11-08), případně až z podstránky,
3. další stránky seznamu se najdou podle parametru stránkování (pg, page, p, strana…),
4. samotné video stáhne yt-dlp z adresy dílu (najde vložené YouTube / Vimeo / mp4).
Funguje jen pro weby, jejichž seznam je v běžném HTML (ne vykreslovaný JavaScriptem).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import logging
import re
from collections import defaultdict
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

from . import netsafe

log = logging.getLogger("viddown.pagelist")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
PAGE_PARAMS = ("pg", "page", "p", "strana", "paged", "pagenum", "stranka", "pagina", "seite")
GENERIC_TEXT = {"zobraziť video", "zobrazit video", "zobrazit", "více", "vice", "viac", "more", "read more", "video", "play", "detail"}
MAX_BYTES = 3_000_000

_DATE_DMY = re.compile(r"(?<!\d)(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(20\d{2}|19\d{2})(?!\d)")
_DATE_ISO = re.compile(r"(?<!\d)(20\d{2}|19\d{2})-(\d{2})-(\d{2})(?!\d)")


class PageError(Exception):
    pass


# ------------------------------------------------------------ stahování a rozbor HTML
async def fetch(url: str, settings: dict | None = None, timeout: float = 30, public_only: bool = False,
                total_timeout: float = 90.0) -> tuple[str, str]:
    """Stáhne HTML. Vrací (text, konečná URL). `public_only`: adresa pochází z cizí stránky, takže každý požadavek včetně přesměrování
    musí mířit na veřejnou adresu (nic z vnitřní sítě). `total_timeout`: server posílající data po kapkách nezdrží volajícího navždy."""
    try:
        return await asyncio.wait_for(_fetch(url, settings, timeout, public_only), total_timeout)
    except asyncio.TimeoutError:
        raise PageError("stránku se nepodařilo načíst: vypršel celkový čas") from None


async def _fetch(url: str, settings: dict | None, timeout: float, public_only: bool) -> tuple[str, str]:
    kw: dict = {}
    if public_only:
        async def only_public(request):
            if not await asyncio.to_thread(netsafe.host_ok, str(request.url)):
                raise PageError("adresa vede do vnitřní sítě")
        kw["event_hooks"] = {"request": [only_public]}
    try:
        kw.update(netsafe.proxy_kw((settings or {}).get("proxy")))
    except netsafe.ProxyError as e:
        raise PageError(f"stránku se nepodařilo načíst: {e}") from e
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers={"User-Agent": UA, "Accept-Language": "cs,sk,en;q=0.8"}, **kw) as c:
            async with c.stream("GET", url) as r:
                if r.status_code >= 400:
                    raise PageError(f"stránka vrací chybu HTTP {r.status_code}")
                ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ctype and not (ctype.startswith("text/") or "html" in ctype or "xml" in ctype):
                    raise PageError(f"adresa nevede na webovou stránku ({ctype})")
                body = bytearray()
                async for chunk in r.aiter_bytes():          # velký soubor se nenačítá celý do paměti
                    body += chunk
                    if len(body) >= MAX_BYTES:
                        break
                final = str(r.url)
                enc = r.encoding or "utf-8"
    except httpx.HTTPError as e:
        raise PageError(f"stránku se nepodařilo načíst: {e}") from e
    return bytes(body[:MAX_BYTES]).decode(enc, errors="replace"), final


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []   # (href, text)
        self.base: str | None = None
        self.title = ""
        self._stack: list[list] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "base" and a.get("href"):
            self.base = a["href"]
        elif tag == "title":
            self._in_title = True
        elif tag in ("script", "style"):
            self._skip += 1
        elif tag == "a" and a.get("href"):
            self._stack.append([a["href"], []])
        elif tag == "img" and self._stack and a.get("alt"):
            self._stack[-1][1].append(a["alt"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._stack:
            href, parts = self._stack.pop()
            self.links.append((href, re.sub(r"\s+", " ", " ".join(parts)).strip()))

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._stack:
            self._stack[-1][1].append(data)


def parse_links(text: str, page_url: str) -> tuple[list[tuple[str, str]], str]:
    p = _Links()
    p.feed(text)
    base = urljoin(page_url, p.base) if p.base else page_url
    out = []
    for href, label in p.links:
        href = html.unescape(href.strip())
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        u = urljoin(base, href).split("#")[0]
        if u.startswith("http"):
            out.append((u, label))
    return out, re.sub(r"\s+", " ", p.title).strip()


def find_date(text: str) -> str | None:
    """Datum z textu: 8.11.2026 nebo 2026-11-08 → 'YYYY-MM-DD'."""
    for m in _DATE_ISO.finditer(text or ""):
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            pass
    for m in _DATE_DMY.finditer(text or ""):
        try:
            return dt.date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        except ValueError:
            pass
    return None


def page_date(text: str) -> str | None:
    """Datum zveřejnění z podstránky: meta tagy, <time>, JSON-LD."""
    for pat in (r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*property=["\']article:published_time',
                r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)',
                r'<time[^>]*datetime=["\']([^"\']+)', r'"datePublished"\s*:\s*"([^"]+)"'):
        m = re.search(pat, text, re.I)
        if m and (d := find_date(m[1])):
            return d
    return None


# ------------------------------------------------------------ detekce vzoru odkazů
def canonical(u: str) -> str:
    """Adresa dílu bez parametru stránkování: týž díl se na různých stránkách seznamu odkazuje s různým `pg`."""
    p = urlparse(u)
    q = [(a, b) for a, b in parse_qsl(p.query, keep_blank_values=True) if a.lower() not in PAGE_PARAMS]
    return urlunparse(p._replace(query=urlencode(q)))


def _norm(u: str) -> tuple[str, str, list[tuple[str, str]]]:
    p = urlparse(u)
    return p.netloc.lower(), p.path, parse_qsl(p.query, keep_blank_values=True)


def _group_key(u: str):
    host, path, q = _norm(u)
    if q:
        return ("q", host, path, tuple(sorted(k for k, _ in q)))
    parent = path.rsplit("/", 1)[0] if "/" in path.strip("/") or path.count("/") > 1 else ""
    return ("p", host, parent, ())


def _regex_for(key, varying: str | None, origin: str) -> str:
    kind, host, path, keys = key
    if kind == "q":
        return rf"^{re.escape(origin)}{re.escape(path)}\?(?=.*(?:^|&){re.escape(varying or keys[0])}=)"
    return rf"^{re.escape(origin)}{re.escape(path)}/[^/?#]+/?$"


def detect(text: str, page_url: str) -> dict:
    """Najde na stránce seznam dílů a stránkování. Vrací {"item_regex", "page_param", "page_start", "items", "title"}."""
    links, title = parse_links(text, page_url)
    origin = "{0.scheme}://{0.netloc}".format(urlparse(page_url))
    best: dict[str, str] = {}
    for u, label in links:                      # k jedné adrese vybereme nejlepší text (ne „Zobrazit video“, ne prázdný)
        lab = label.strip()
        cur = best.get(u, "")
        good = lab and lab.lower() not in GENERIC_TEXT
        if good and (not cur or cur.lower() in GENERIC_TEXT or len(lab) > len(cur)):
            best[u] = lab
        elif u not in best:
            best[u] = lab
    groups: dict = defaultdict(list)
    for u in best:
        groups[_group_key(u)].append(u)
    here = _group_key(page_url)
    scored = []
    for key, urls in groups.items():
        if len(urls) < 2:
            continue
        labels = [best[u] for u in urls if best[u] and best[u].lower() not in GENERIC_TEXT]
        dated = sum(1 for x in labels if find_date(x))
        score = len(urls) + 3 * dated + len(labels) * 0.5
        # stránkovací odkazy (stejná stránka, mění se jen číslo) nejsou díly
        if key[0] == "q" and key == here and not any(k == "video" for k in key[3]) and dated == 0:
            score *= 0.2
        scored.append((score, key, urls))
    if not scored:
        raise PageError("na stránce jsem nenašel opakující se odkazy na videa")
    scored.sort(key=lambda x: -x[0])
    _, key, urls = scored[0]
    varying = None
    if key[0] == "q":
        vals = defaultdict(set)
        for u in urls:
            for k, v in _norm(u)[2]:
                vals[k].add(v)
        varying = max(vals, key=lambda k: len(vals[k]))
        if len(vals[varying]) < 2:
            raise PageError("nepodařilo se určit, který parametr odkazu rozlišuje jednotlivá videa")
    regex = _regex_for(key, varying, origin)
    # stránkování: odkazy na tutéž stránku s různou číselnou hodnotou některého parametru
    host, path, q = _norm(page_url)
    pvals: dict[str, set[int]] = defaultdict(set)
    for u in best:
        h, p, qq = _norm(u)
        if h == host and p == path:
            for k, v in qq:
                if k.lower() in PAGE_PARAMS and v.isdigit():
                    pvals[k].add(int(v))
    page_param, start = None, 0
    if pvals:
        page_param = max(pvals, key=lambda k: len(pvals[k]))
        mn = min(v for v in pvals[page_param] if v > 0) if any(v > 0 for v in pvals[page_param]) else 1
        start = max(0, mn - 1)
    template = None
    if page_param:
        # odkaz na další stránku seznamu (zachová ostatní parametry, třeba id sekce) s číslem nahrazeným {n}
        cand = sorted((u for u in best if _norm(u)[0] == host and _norm(u)[1] == path
                       and any(k == page_param and v.isdigit() and int(v) > start for k, v in _norm(u)[2])
                       and not any(k == "video" for k, _ in _norm(u)[2])), key=len)
        if cand:
            pu = urlparse(cand[0])
            qq = [(k, "{n}" if k == page_param else v) for k, v in parse_qsl(pu.query, keep_blank_values=True)]
            template = urlunparse(pu._replace(query="&".join(f"{k}={v}" for k, v in qq)))
    seen_c, items = set(), []
    for u in urls:
        c = canonical(u)
        if c in seen_c:
            continue
        seen_c.add(c)
        items.append({"url": c, "title": best[u], "date": find_date(best[u])})
    return {"item_regex": regex, "page_param": page_param, "page_start": start, "page_template": template,
            "items": items, "title": title}


# ------------------------------------------------------------ procházení stránek
def page_url(base: str, cfg: dict, k: int) -> str:
    """Adresa k-té stránky seznamu (k = 0 je zadaná adresa)."""
    if k == 0:
        return base
    start = int(cfg.get("page_start") or 0)
    if cfg.get("page_template"):
        return cfg["page_template"].replace("{n}", str(start + k))
    param = cfg.get("page_param")
    if not param:
        return base
    p = urlparse(base)
    q = [(a, b) for a, b in parse_qsl(p.query, keep_blank_values=True) if a != param]
    q.append((param, str(start + k)))
    return urlunparse(p._replace(query=urlencode(q)))


def items_from(text: str, url: str, regex: str) -> list[dict]:
    links, _ = parse_links(text, url)
    rx = re.compile(regex)
    best: dict[str, str] = {}
    order: list[str] = []
    for u, label in links:
        if not rx.search(u):
            continue
        if u not in best:
            order.append(u)
        lab = label.strip()
        if lab and lab.lower() not in GENERIC_TEXT and len(lab) > len(best.get(u, "")):
            best[u] = lab
        else:
            best.setdefault(u, "")
    out, seen = [], set()
    for u in order:
        c = canonical(u)
        if c in seen:
            continue
        seen.add(c)
        out.append({"url": c, "id": c, "title": best[u] or None, "date": find_date(best[u])})
    return out


async def list_items(sub: dict, ctx, max_pages: int, since: str | None = None) -> list[dict]:
    """Díly seznamu od nejnovějších. Další stránky se čtou, dokud přinášejí nové odkazy a (při zadaném datu)
    dokud na stránce není aspoň jeden díl novější než `since` nebo bez data."""
    cfg = json.loads(sub["config"]) if sub.get("config") else {}
    regex = cfg.get("item_regex")
    if not regex:
        raise PageError("odběr nemá nastaven vzor odkazů na videa")
    out: list[dict] = []
    seen: set[str] = set()
    for k in range(max_pages):
        url = page_url(sub["url"], cfg, k)
        text, final = await fetch(url, ctx.settings)
        items = [i for i in items_from(text, final, regex) if i["url"] not in seen]
        if not items:
            break
        seen.update(i["url"] for i in items)
        out += items
        if not cfg.get("page_param") and not cfg.get("page_template"):
            break
        if since and all(i["date"] and i["date"] < since for i in items):
            break
    return out


async def analyze(url: str, settings: dict | None = None) -> dict:
    text, final = await fetch(url, settings)
    return detect(text, final)
