"""Vlastní HLS sniffer: headless Chromium načte stránku a odposlouchává síťové odpovědi.

Inspirace: puemos/hls-downloader (detekce podle MIME typu a přípony .m3u8, RFC 8216).
Nalezený stream stáhne a spojí ffmpeg (-c copy).
"""
from __future__ import annotations

import asyncio
import signal
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .. import netsafe
from ..util import classify_error, is_hls_response
from . import Cancelled, Ctx, ProcHolder, ResolveError, _signal_group, cookiepolicy, spawn_proc

log = logging.getLogger("viddown.sniffer")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

INIT_JS = """
(() => { try {
  const orig = navigator.requestMediaKeySystemAccess;
  if (orig) navigator.requestMediaKeySystemAccess = function(k, c) { window.__vd_drm = k; return orig.call(this, k, c); };
} catch (e) {} })();
"""

META_JS = """() => {
  const q = s => document.querySelector(s);
  const vids = Array.from(document.querySelectorAll('video'));
  return {
    title: (q('meta[property="og:title"]') || {}).content || document.title || '',
    image: (q('meta[property="og:image"]') || {}).content || null,
    poster: vids.map(v => v.poster).find(Boolean) || null,
    drm: window.__vd_drm || null,
    srcs: vids.map(v => v.currentSrc || v.src).filter(s => s && !s.startsWith('blob:') && !s.startsWith('data:')),
  };
}"""

PLAY_JS = """() => {
  let n = 0;
  for (const v of document.querySelectorAll('video')) { try { v.muted = true; v.play(); n++; } catch (e) {} }
  return n;
}"""

DIRECT_EXT = re.compile(r"\.(mp4|webm|mov|m4v|mkv)$", re.I)
SEGMENT_EXT = re.compile(r"\.(ts|m4s|aac|m4a|vtt|key)$", re.I)

# Zástupné soubory přehrávačů (černé video při startu) a reklamní servery – nejsou to hledaná videa.
JUNK_BYTES = 50_000
PLACEHOLDER_RE = re.compile(r"(^|/)(black\d*|blank|empty|placeholder|dummy)\.(mp4|webm|m4v)$", re.I)
AD_HOST_RE = re.compile(r"(flashtalking|doubleclick|googlesyndication|2mdn\.net|adform|adnxs|innovid|"
                        r"imasdk|moatads|teads|smartadserver|adition)", re.I)

# Okno souhlasu s cookies blokuje přehrávač. Volíme nejstřídmější variantu: odmítnout nepovinné.
CONSENT_JS = """() => {
  try { if (window.Didomi && Didomi.setUserDisagreeToAll) { Didomi.setUserDisagreeToAll(); return 'didomi'; } } catch (e) {}
  const sel = ['#onetrust-reject-all-handler', '#CybotCookiebotDialogBodyButtonDecline', '.fc-cta-do-not-consent',
               '#didomi-notice-disagree-button', 'button[aria-label*="zamítnout" i]', 'button[aria-label*="reject" i]'];
  for (const s of sel) { const e = document.querySelector(s); if (e) { e.click(); return s; } }
  const re = /^(zamítnout vše|odmítnout vše|odmítnout|pokračovat bez souhlasu|reject all|decline all|only necessary)$/i;
  for (const e of document.querySelectorAll('button, a, [role=button]')) {
    if (re.test((e.innerText || '').trim())) { e.click(); return 'text'; }
  }
  return null;
}"""

SKIP_AD_JS = """() => {
  const re = /^(přeskočit( reklamu)?|pomiń reklamę|preskočiť( reklamu)?|skip ads?)$/i;
  for (const e of document.querySelectorAll('#skipAction, button, [role=button]')) {
    const t = (e.innerText || '').trim();
    if (e.id === 'skipAction' || re.test(t)) { try { e.click(); return true; } catch (x) {} }
  }
  return false;
}"""


def implausible_size(size: int, duration: float | None) -> str | None:
    """Vrátí text chyby, když je stažený soubor zjevně prázdný/zástupný (např. 2 kB místo videa)."""
    if size < JUNK_BYTES:
        return f"stažený soubor je příliš malý ({size} B) – nejde o skutečné video"
    if duration and duration > 60 and size < duration * 5_000:
        return f"stažený soubor ({size // 1024} kB) je na {int(duration)} s videa příliš malý"
    return None


def is_junk_direct(url: str, length: int) -> bool:
    """Zástupný/reklamní „přímý“ soubor, který nemá být kandidátem ke stažení."""
    u = urlparse(url)
    if PLACEHOLDER_RE.search(u.path) or AD_HOST_RE.search(u.netloc):
        return True
    return 0 < length < JUNK_BYTES


EVAL_TIMEOUT = 15.0     # stránka s nekonečnou smyčkou v JS nesmí zastavit sniff ani katalog navždy


async def _ev(target, js: str, timeout: float = EVAL_TIMEOUT):
    """`evaluate` s časovým limitem (stránka nebo rámec)."""
    return await asyncio.wait_for(target.evaluate(js), timeout)


async def _in_frames(page, js: str):
    """Spustí JS ve všech rámcích stránky, vrátí první pravdivý výsledek."""
    for fr in page.frames:
        try:
            r = await _ev(fr, js)
        except Exception:  # noqa: BLE001
            continue
        if r:
            return r
    return None


def parse_netscape_cookies(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        dom, _, path_, secure, exp, name, value = parts[:7]
        c = {"name": name, "value": value, "domain": dom, "path": path_ or "/", "secure": secure.upper() == "TRUE"}
        try:
            e = int(float(exp))
            if e > 10 ** 11:  # některé exporty (Firefox) mají čas v milisekundách
                e //= 1000
            if e > 0:
                c["expires"] = e
        except ValueError:
            pass
        out.append(c)
    return out


def cookie_applies(domain: str, host: str) -> bool:
    d = (domain or "").lstrip(".").lower()
    h = (host or "").lower()
    return bool(d) and (h == d or h.endswith("." + d))


async def add_cookies(context, path: Path, host: str | None = None) -> int:
    """Načte cookies.txt do prohlížeče po jedné; vadná položka nezahodí ostatní. S `host` se načtou jen cookies, které platí pro
    tento web (ostatní přihlášení z cookies.txt do prohlížeče nepatří). Vrací počet načtených."""
    ok = bad = 0
    for ck in parse_netscape_cookies(path):
        if host is not None and not cookie_applies(ck["domain"], host):
            continue
        try:
            await context.add_cookies([ck])
            ok += 1
        except Exception:  # noqa: BLE001
            bad += 1
    if bad:
        log.warning("cookies: %d položek se nepodařilo načíst do prohlížeče, přeskočeno", bad)
    return ok


def parse_m3u8(text: str, base: str) -> dict:
    """Rozpozná master/media playlist. U master vybere variantu s nejvyšším datovým tokem."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    res = {"master": False, "variants": [], "audio": {}, "duration": 0.0, "drm": False, "live": False}
    attrs_re = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
    for i, l in enumerate(lines):
        if l.startswith("#EXT-X-STREAM-INF"):
            res["master"] = True
            a = {k: v.strip('"') for k, v in attrs_re.findall(l.split(":", 1)[1])}
            uri = next((x for x in lines[i + 1:] if not x.startswith("#")), None)
            if uri:
                h = None
                if "RESOLUTION" in a and "x" in a["RESOLUTION"]:
                    h = int(a["RESOLUTION"].split("x")[1])
                res["variants"].append({"uri": urljoin(base, uri), "bw": int(a.get("BANDWIDTH", 0) or 0),
                                        "height": h, "audio": a.get("AUDIO")})
        elif l.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in l:
            a = {k: v.strip('"') for k, v in attrs_re.findall(l.split(":", 1)[1])}
            if a.get("URI"):
                g = a.get("GROUP-ID")
                if g not in res["audio"] or a.get("DEFAULT") == "YES":
                    res["audio"][g] = urljoin(base, a["URI"])
        elif l.startswith("#EXTINF"):
            try:
                res["duration"] += float(l.split(":", 1)[1].split(",")[0])
            except ValueError:
                pass
        elif l.startswith("#EXT-X-KEY") or l.startswith("#EXT-X-SESSION-KEY"):
            if re.search(r"SAMPLE-AES|com\.apple\.streamingkeydelivery|com\.widevine|playready", l, re.I):
                res["drm"] = True
    # media playlist bez #EXT-X-ENDLIST je živý přenos (pořád se prodlužuje): ffmpeg by ho stahoval donekonečna
    res["live"] = not res["master"] and any(l.startswith("#EXTINF") for l in lines) and not any(l.startswith("#EXT-X-ENDLIST") for l in lines)
    if res["variants"]:
        best = max(res["variants"], key=lambda v: (v["height"] or 0, v["bw"]))
        res["best"] = best
        res["best_audio"] = res["audio"].get(best.get("audio")) if best.get("audio") else None
    return res


DASH_DRM_RE = re.compile(r"<ContentProtection\b[^>]*schemeIdUri=\"urn:uuid:", re.I)     # Widevine/PlayReady/FairPlay (ne jen „mp4protection“)
MAX_STREAMS = 8          # nejvýš tolik nalezených playlistů se při sniffu zkoumá (stránka jich může nahrát stovky)


def media_kind(url: str) -> str | None:
    """Adresa přímo na mediální soubor nebo playlist (pak se stránka nevykresluje, prohlížeč by soubor jen stáhl)."""
    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return None
    if path.endswith(".m3u8"):
        return "hls"
    if path.endswith(".mpd"):
        return "dash"
    return "direct" if DIRECT_EXT.search(path) else None


def mask_urls(text: str) -> str:
    """Podepsané adresy (tokeny v parametrech) do chybových hlášek, logu ani Telegramu nepatří."""
    return re.sub(r"(https?://[^\s?#]+)[?#][^\s'\"]*", r"\1?…", text or "")


class Renderer:
    """Jeden headless Chromium pro vykreslení více stránek po sobě (`async with Renderer(ctx) as r: await r.render(url)`)."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self._pw = self._browser = self._context = None
        self._ck_hosts: set[str] | None = None        # režim „cookies jen když je potřeba“: weby, jejichž cookies už jsou načtené

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise ResolveError(f"Playwright není nainstalován: {e}", "engine")
        s = self.ctx.settings
        self._pw = await async_playwright().start()
        kw = {"headless": True}
        if s.get("proxy"):
            kw["proxy"] = {"server": s["proxy"]}
        try:
            self._browser = await self._pw.chromium.launch(**kw)
        except BaseException as e:                                  # i zrušení (CancelledError): ovladač Playwright se zastaví
            await self._pw.stop()
            if isinstance(e, Exception):
                raise ResolveError(f"Chromium nelze spustit ({e}). Nainstalujte ho v Enginy.", "engine")
            raise
        try:
            self._context = await self._browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, locale="cs-CZ")
            if self.ctx.cookies_file:
                if cookiepolicy.needed_mode(self.ctx.settings) and self.ctx.no_cookies is None:
                    self._ck_hosts = set()                                  # cookies se přidají až pro web, který je potřebuje
                else:
                    await add_cookies(self._context, self.ctx.cookies_file)
        except BaseException:                                       # `__aexit__` se po neúspěšném vstupu nevolá: prohlížeč i ovladač se zavřou tady
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *exc):
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def render(self, url: str, scrolls: int = 6) -> tuple[str, str]:
        """Načte stránku (včetně obsahu vykresleného JavaScriptem), postupně ji odroluje kvůli líně načítaným seznamům
        a vrátí (HTML, konečná adresa)."""
        from playwright.async_api import TimeoutError as PWTimeout
        timeout = float(self.ctx.settings.get("sniff_timeout", 40))
        if self._ck_hosts is not None and self.ctx.cookies_file and cookiepolicy.wanted(self.ctx, url):
            host = (urlparse(url).hostname or "").lower()
            if host and host not in self._ck_hosts:
                self._ck_hosts.add(host)
                await add_cookies(self._context, self.ctx.cookies_file, host)
        page = await self._context.new_page()
        try:
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            except PWTimeout:
                resp = None
            except Exception as e:  # noqa: BLE001
                msg = str(e).splitlines()[0]
                raise ResolveError(f"stránku nelze načíst: {msg}", classify_error(msg))
            if resp is not None and resp.status >= 400:             # chybová stránka nebo captcha není seznam: ať se nevyhodnotí jako „úplný seznam bez videí“
                raise ResolveError(f"stránka vrací chybu HTTP {resp.status}", "network")
            await page.wait_for_timeout(2000)
            await _in_frames(page, CONSENT_JS)
            last = 0
            for _ in range(scrolls):
                try:
                    h = await _ev(page, "() => { window.scrollTo(0, document.body.scrollHeight); return document.body.scrollHeight; }")
                except Exception:  # noqa: BLE001
                    break
                await page.wait_for_timeout(1000)
                if h == last:
                    break
                last = h
            return await page.content(), page.url
        finally:
            await page.close()


async def render_html(url: str, ctx: Ctx, scrolls: int = 6) -> tuple[str, str]:
    """Vykreslí jednu stránku vlastním prohlížečem (viz `Renderer`)."""
    async with Renderer(ctx) as r:
        return await r.render(url, scrolls)


async def guard_routes(context, start_url: str) -> None:
    """Prohlížeč smí jen na veřejné weby (ne do místní sítě, na metadata cloudu, `file:` apod.). Web, který uživatel zadal, se nekontroluje;
    přesměrování a podpožadavky na jiné adresy ano (stránka z internetu jinak může skenovat místní síť)."""
    start_host = (urlparse(start_url).hostname or "").lower()
    cache: dict[str, bool] = {start_host: True}

    async def handler(route):
        u = route.request.url
        if u.startswith(("data:", "blob:", "about:")):
            await route.continue_()
            return
        try:
            host = (urlparse(u).hostname or "").lower()
        except ValueError:
            host = ""
        if not u.startswith(("http://", "https://")) or not host:
            await route.abort()
            return
        ok = cache.get(host)
        if ok is None:
            ok = await asyncio.to_thread(netsafe.host_ok, u)
            cache[host] = ok
            if not ok:
                log.warning("sniffer: požadavek na neveřejnou adresu zablokován (%s)", host)
        if ok:
            await route.continue_()
        else:
            await route.abort()
    await context.route("**/*", handler)


async def _get(context, u: str, referer: str):
    """Dotaz mimo prohlížeč (context.request) obchází `guard_routes`, proto se veřejnost adresy ověřuje tady.
    Stejný hostitel jako stránka se nekontroluje (web, který uživatel zadal, se kontroluje jen při přesměrování a podpožadavcích)."""
    rh = (urlparse(referer).hostname or "").lower()
    cur = u
    for _ in range(MAX_REDIRECTS + 1):
        # každý krok (i přesměrování) se ověří zvlášť: přesměrování na vnitřní adresu nesmí projít
        if (urlparse(cur).hostname or "").lower() != rh and not await asyncio.to_thread(netsafe.host_ok, cur):
            raise ValueError("adresa mimo veřejný internet")
        r = await context.request.get(cur, headers={"Referer": referer}, timeout=20000, max_redirects=0)
        loc = r.headers.get("location") if r.status in (301, 302, 303, 307, 308) else None
        if not loc:
            return r
        cur = urljoin(cur, loc)
    raise ValueError("příliš mnoho přesměrování")


MAX_REDIRECTS = 5


MAX_PLAYLISTS = 12
MAX_PLAYLIST_URIS = 20000


async def hls_hosts_ok(url: str, referer: str, depth: int = 0, headers: dict | None = None, proxy: str | None = None) -> bool:
    """Ffmpeg sám stahuje segmenty a varianty z playlistu, takže se každá adresa v něm ověří předem (jen hostitelé jiní než
    hostitel playlistu; ten se ověřil u kandidáta). Vnořené playlisty se procházejí do malé hloubky."""
    if depth > 2:
        return False
    try:
        res = await asyncio.to_thread(netsafe.fetch_limited, url, {"Referer": referer, "User-Agent": UA, **(headers or {})}, 5 * 1024 * 1024, proxy, 30.0)
    except Exception:  # noqa: BLE001 - síťová chyba jen vyřadí tohoto kandidáta, ne celé stahování
        return False
    if res is None or res[0] >= 400:
        return False
    text = res[2].decode("utf-8", "replace")
    own = (urlparse(url).hostname or "").lower()
    uris: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            uris += re.findall(r'URI="([^"]+)"', line)
        else:
            uris.append(line)
    if len(uris) > MAX_PLAYLIST_URIS:
        return False
    hosts: set[str] = set()
    subs: list[str] = []
    for u in uris:
        absu = urljoin(url, u)
        if not absu.lower().startswith(("http://", "https://")):
            return False                                    # jiné schéma (file:, data:…) v playlistu nepatří do stahování
        h = (urlparse(absu).hostname or "").lower()
        if h and h != own:
            hosts.add(h)
        if ".m3u8" in absu.lower().split("?")[0]:
            subs.append(absu)
    for h in hosts:                                         # každý jiný hostitel se ověří jednou (DNS se nekupí)
        if not await asyncio.to_thread(netsafe.host_ok, f"https://{h}/"):
            return False
    if len(subs) > MAX_PLAYLISTS:
        return False
    for sp in subs:
        if not await hls_hosts_ok(sp, referer, depth + 1, headers, proxy):
            return False
    return True


async def candidate_ok(url: str, referer: str) -> bool:
    """Adresa kandidáta pro ffmpeg: jen http(s) a veřejný hostitel (nebo stejný web, jaký uživatel zadal)."""
    try:
        h = (urlparse(url).hostname or "").lower()
        rh = (urlparse(referer).hostname or "").lower()
    except ValueError:
        return False
    if not url.lower().startswith(("http://", "https://")) or not h:
        return False
    return h == rh or await asyncio.to_thread(netsafe.host_ok, url)


async def sniff(url: str, ctx: Ctx) -> dict:
    """Načte stránku a vrátí {title, thumbnail, candidates[], drm, headers}. Cookies podle `cookiepolicy` (při „jen když je
    potřeba“ se stránka bez nalezeného videa zkusí jednou znovu s cookies, pokud cookies.txt obsahuje přihlášení k tomuto webu)."""
    return await cookiepolicy.attempt(ctx, url, lambda c: _sniff(url, c),
                                      empty=lambda sn: not sn.get("candidates") and not sn.get("drm"))


async def _sniff(url: str, ctx: Ctx) -> dict:
    try:
        from playwright.async_api import TimeoutError as PWTimeout
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise ResolveError(f"Playwright není nainstalován: {e}", "engine")
    s = ctx.settings
    timeout = float(s.get("sniff_timeout", 40))
    found: dict[str, dict] = {}

    async with async_playwright() as p:
        kw = {"headless": True}
        if s.get("proxy"):
            kw["proxy"] = {"server": s["proxy"]}
        try:
            browser = await p.chromium.launch(**kw)
        except Exception as e:  # noqa: BLE001
            raise ResolveError(f"Chromium nelze spustit ({e}). Nainstalujte ho v Enginy.", "engine")
        try:
            context = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720},
                                                ignore_https_errors=True, locale="cs-CZ")
            if ctx.cookies_file:
                await add_cookies(context, ctx.cookies_file, urlparse(url).hostname or "")
            await guard_routes(context, url)
            await context.add_init_script(INIT_JS)
            page = await context.new_page()

            def on_response(resp):
                try:
                    u = resp.url
                    if not u.startswith("http") or resp.status >= 400:        # chybová odpověď (404, 403…) není video
                        return
                    ct = (resp.headers.get("content-type") or "").lower()
                    path = urlparse(u).path
                    if is_hls_response(u, ct):
                        found.setdefault(u, {"kind": "hls", "t": time.monotonic()})
                    elif "dash+xml" in ct or path.lower().endswith(".mpd"):
                        found.setdefault(u, {"kind": "dash", "t": time.monotonic()})
                    elif (ct.startswith("video/") or DIRECT_EXT.search(path)) and not SEGMENT_EXT.search(path):
                        ln = int(resp.headers.get("content-length") or 0)
                        rng = resp.headers.get("content-range") or ""
                        if "/" in rng:
                            try:
                                ln = int(rng.rsplit("/", 1)[1])
                            except ValueError:
                                pass
                        if not is_junk_direct(u, ln):
                            found.setdefault(u, {"kind": "direct", "len": ln, "t": time.monotonic()})
                except Exception:  # noqa: BLE001
                    pass

            page.on("response", on_response)
            start = time.monotonic()
            mk = media_kind(url)
            if mk:                                                          # odkaz rovnou na video nebo playlist: žádná stránka
                found[url] = {"kind": mk, "len": 0, "t": time.monotonic() - 10}
                timeout = 0
            try:
                if not mk:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            except PWTimeout:
                pass
            except Exception as e:  # noqa: BLE001
                msg = str(e).splitlines()[0]
                raise ResolveError(f"stránku nelze načíst: {msg}", classify_error(msg))
            consent_done, clicks, last_click = False, 0, 0.0
            while time.monotonic() - start < timeout:
                await page.wait_for_timeout(1000)
                now = time.monotonic()
                streams = [c for c in found.values() if c["kind"] in ("hls", "dash")]
                if streams and now - min(c["t"] for c in streams) > 2.5:
                    break
                directs = [c for c in found.values() if c["kind"] == "direct"]
                if directs and not streams and now - min(c["t"] for c in directs) > 5:
                    break
                if not consent_done and now - start < 15:
                    how = await _in_frames(page, CONSENT_JS)
                    if how:
                        consent_done = True
                        log.info("sniffer: okno souhlasu odmítnuto (%s)", how)
                        await page.wait_for_timeout(1500)
                if clicks:
                    await _in_frames(page, SKIP_AD_JS)  # předřazená reklama se přeskočí, jakmile to jde
                # klik na přehrávač: nejdřív po vyřešení souhlasu (nebo po 3 s), případně znovu po 12 s
                if clicks < 3 and (consent_done or now - start > 3) and now - last_click > 12 and not streams:
                    clicks += 1
                    last_click = now
                    try:
                        n = await _ev(page, PLAY_JS)
                        if not n:
                            # klik doprostřed největšího přehrávače / iframu (po odrolování do zorného pole)
                            box = await page.evaluate("""() => {
                              const els = Array.from(document.querySelectorAll('video, iframe, [class*=player], [id*=player]'));
                              let best = null, area = 0;
                              for (const e of els) { const r = e.getBoundingClientRect(); const a = r.width * r.height;
                                if (a > area && r.width > 100 && r.height > 60) { area = a; best = e; } }
                              if (!best) return null;
                              best.scrollIntoView({block: 'center'});
                              const r = best.getBoundingClientRect();
                              return {x: r.x + r.width/2, y: r.y + r.height/2}; }""")
                            if box:
                                await page.mouse.click(box["x"], box["y"])
                    except Exception:  # noqa: BLE001
                        pass
            try:
                meta = await _ev(page, META_JS)
            except Exception:  # noqa: BLE001
                meta = {"title": "", "image": None, "poster": None, "drm": None, "srcs": []}
            for src in meta.get("srcs") or []:
                if not isinstance(src, str) or not src.lower().startswith(("http://", "https://")) or is_junk_direct(src, 0):
                    continue                                              # file:, concat: a jiná schémata by ffmpeg četl z disku kontejneru
                found.setdefault(src, {"kind": "direct", "len": 0, "t": time.monotonic()})

            candidates = []
            drm = bool(meta.get("drm"))
            variant_urls: set[str] = set()
            hls_urls = [u for u, c in found.items() if c["kind"] == "hls"][:MAX_STREAMS]
            for u in hls_urls:
                try:
                    r = await _get(context, u, url)
                    pl = parse_m3u8(await r.text(), u)
                except Exception:  # noqa: BLE001
                    continue
                if pl["drm"]:
                    drm = True
                    continue
                if pl["master"]:
                    best = pl.get("best")
                    if not best:                                                       # master bez použitelné varianty nesmí shodit celý sniff
                        continue
                    variant_urls.update(v["uri"] for v in pl["variants"])
                    live = False
                    try:                                                               # šifrování bývá až v playlistu vybrané varianty, ne v master playlistu
                        vr = await _get(context, best["uri"], url)
                        vp = parse_m3u8(await vr.text(), best["uri"])
                        if vp["drm"]:
                            drm = True
                            continue
                        live = vp["live"]
                    except Exception:  # noqa: BLE001
                        pass
                    candidates.append({"kind": "hls", "url": best["uri"], "audio": pl.get("best_audio"),
                                       "height": best["height"], "master": u, "rank": 0, "live": live})
                else:
                    candidates.append({"kind": "hls", "url": u, "audio": None, "height": None,
                                       "duration": pl["duration"], "rank": 2, "live": pl["live"]})
            candidates = [c for c in candidates if c["rank"] == 0 or c["url"] not in variant_urls]
            for u in [u for u, c in found.items() if c["kind"] == "dash"][:MAX_STREAMS]:
                try:                                                               # šifrovaný DASH by se stáhl jako nepřehratelný soubor
                    mr = await _get(context, u, url)
                    mpd = await mr.text()
                    if DASH_DRM_RE.search(mpd):
                        drm = True
                        continue
                    live = 'type="dynamic"' in mpd
                except Exception:  # noqa: BLE001
                    live = False
                candidates.append({"kind": "dash", "url": u, "height": None, "rank": 1, "live": live})
            for u, c in found.items():
                if c["kind"] == "dash":
                    continue
                elif c["kind"] == "direct":
                    candidates.append({"kind": "direct", "url": u, "height": None, "len": c.get("len", 0), "rank": 3})
            candidates.sort(key=lambda c: (c["rank"], -(c.get("height") or 0), -(c.get("len") or 0)))
            cookies = await context.cookies()
        finally:
            await browser.close()

    thumb = meta.get("image") or meta.get("poster")
    if thumb:
        thumb = urljoin(url, thumb)
    return {"title": (meta.get("title") or "").strip(), "thumbnail": thumb, "candidates": candidates,
            "drm": drm, "referer": url, "cookies": cookies}


def _cookie_header(cookies: list[dict], target: str) -> str:
    host = urlparse(target).hostname or ""
    pairs = []
    for c in cookies or []:
        d = (c.get("domain") or "").lstrip(".")
        if d and (host == d or host.endswith("." + d)):
            pairs.append(f"{c['name']}={c['value']}")
    return "; ".join(pairs)


WHITELIST = "http,https,tcp,tls,crypto"                                # ffmpeg nesmí z playlistu číst `file:`, `concat:` ani jiná schémata


async def _duration(ctx: Ctx, url: str, headers: str) -> float | None:
    fp = ctx.engines.get("ffmpeg").bin_path("ffprobe")
    if not fp:
        return None
    cmd = [fp, "-v", "error", "-user_agent", UA]
    if headers:
        cmd += ["-headers", headers]
    cmd += ["-protocol_whitelist", WHITELIST, "-show_entries", "format=duration", "-of", "csv=p=0", url]
    proc = None
    try:
        proc = await spawn_proc(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 45)
        return float(out.decode().strip())
    except Exception:  # noqa: BLE001
        if proc is not None and proc.returncode is None:               # zaseknutý ffprobe by jinak zůstal běžet jako sirotek
            try:
                _signal_group(proc, signal.SIGKILL)
                await proc.wait()
            except (ProcessLookupError, OSError):
                pass
        return None


async def download(sn: dict, ctx: Ctx, staging: Path, name: str, on_progress, holder: ProcHolder) -> dict:
    """Stáhne nejlepšího kandidáta ze sniffu přes ffmpeg."""
    ff = ctx.engines.get("ffmpeg").bin_path()
    if not ff:
        raise ResolveError("ffmpeg není k dispozici", "engine")
    staging.mkdir(parents=True, exist_ok=True)
    if not sn.get("candidates"):
        raise ResolveError("na stránce nebylo nalezeno žádné video", "unsupported")
    last_err = "neznámá chyba"
    last_kind = None
    for cand in sn["candidates"][:3]:
        if cand.get("live") and not ctx.settings.get("live_from_start"):      # živý přenos by se stahoval donekonečna
            last_err, last_kind = "na stránce je živý přenos (nahrávání živých přenosů je vypnuté)", "live"
            continue
        hdr_lines = [f"Referer: {sn['referer']}"]
        if not await candidate_ok(cand["url"], sn["referer"]) or (cand.get("audio") and not await candidate_ok(cand["audio"], sn["referer"])):
            last_err = "adresa videa míří mimo veřejný internet"
            continue
        ref_host = (urlparse(sn["referer"]).hostname or "").lower()
        playlists = [u for u in [cand["url"], cand.get("audio")] if u and (cand.get("kind") == "hls" or ".m3u8" in u.lower())]
        # playlist na hostiteli, který uživatel zadal (stejný jako stránka), se nekontroluje: jeho obsah ffmpeg stahuje sám
        unsafe = False
        for u in playlists:
            ck_u = _cookie_header(sn.get("cookies"), u)          # CDN může vyžadovat stejné cookies jako prohlížeč
            hdrs = {"Cookie": ck_u} if ck_u else None
            if (urlparse(u).hostname or "").lower() != ref_host and not await hls_hosts_ok(u, sn["referer"], 0, hdrs, ctx.settings.get("proxy") or None):
                unsafe = True
                break
        if unsafe:
            last_err = "playlist odkazuje na adresy mimo veřejný internet"
            continue
        ck = _cookie_header(sn.get("cookies"), cand["url"])
        if ck:
            hdr_lines.append(f"Cookie: {ck}")
        headers = "".join(l + "\r\n" for l in hdr_lines)
        duration = cand.get("duration") or await _duration(ctx, cand["url"], headers)
        is_mp4 = ctx.settings.get("quality") == "compat" or cand["kind"] in ("hls", "dash") or cand["url"].lower().split("?")[0].endswith(".mp4")
        for ext in ([".mp4", ".mkv"] if is_mp4 else [".mkv"]):
            out = staging / f"{name}{ext}"
            cmd = [ff, "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-user_agent", UA, "-headers", headers,
                   "-protocol_whitelist", WHITELIST, "-rw_timeout", "30000000", "-i", cand["url"]]                    # server, který přestane posílat data, nezdrží stahování navždy
            if cand.get("audio"):
                cmd += ["-user_agent", UA, "-headers", headers, "-protocol_whitelist", WHITELIST, "-rw_timeout", "30000000", "-i", cand["audio"], "-map", "0:v:0?", "-map", "1:a:0?"]
            else:
                cmd += ["-map", "0:v:0?", "-map", "0:a:0?"]
            cmd += ["-c", "copy"]
            if ext == ".mp4":
                cmd += ["-bsf:a", "aac_adtstoasc", "-movflags", "+faststart"]
            cmd += ["-progress", "pipe:1", str(out)]
            holder.check()
            proc = await spawn_proc(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await holder.attach(proc)
            err_task = asyncio.create_task(proc.stderr.read())  # type: ignore[union-attr]
            t0, size, last = time.monotonic(), 0, 0.0
            assert proc.stdout
            async for raw in proc.stdout:
                k, _, v = raw.decode(errors="replace").strip().partition("=")
                if k == "total_size" and v.isdigit():
                    size = int(v)
                elif k == "out_time_us" and v.lstrip("-").isdigit():
                    now = time.monotonic()
                    if now - last > 0.5:
                        last = now
                        sec = max(int(v), 0) / 1e6
                        frac = min(sec / duration, 1.0) if duration else None
                        el = now - t0
                        spd = size / el if el > 0 else None
                        eta = int((el / frac) - el) if frac and frac > 0.01 else None
                        on_progress(downloaded=size, total=int(size / frac) if frac and frac > 0.02 else None,
                                    progress=frac, speed=spd, eta=eta)
            code = await proc.wait()
            err = (await err_task).decode(errors="replace").strip()
            holder.proc = None
            if holder.stopped:
                out.unlink(missing_ok=True)                                 # ffmpeg nenavazuje: polotovar by jen zabíral místo
                raise Cancelled()
            if code == 0 and out.exists():
                bad = implausible_size(out.stat().st_size, duration)
                if not bad:
                    return {"file": out, "thumb": None, "log": err}
                last_err = bad
                out.unlink(missing_ok=True)
                break  # stejný zdroj v jiném kontejneru by dopadl stejně
            last_err = mask_urls(err.splitlines()[-1]) if err else f"ffmpeg skončil s kódem {code}"
            out.unlink(missing_ok=True)
    if last_kind == "live" and last_err.startswith("na stránce je živý přenos"):
        raise ResolveError(last_err, "live")
    raise ResolveError(last_err, classify_error(last_err) if classify_error(last_err) != "unsupported" else "other")
