"""Facebook Stories: stránky, které video neobsahují přímo.

open_story() otevře story v prohlížeči (s cookies), odklikne „zobrazit příběh“ a vrátí buď
  - {"link": URL}   – story sdílí reel/video (to pak stáhne yt-dlp jako každé jiné video), nebo
  - {"sniff": {...}} – story má vlastní video: Facebook ho přehrává jako dva MP4 proudy (obraz a zvuk)
                       po kouscích (bytestart/byteend); z nich se složí odkazy na celé soubory pro ffmpeg.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse

from . import ResolveError
from .sniffer import UA, add_cookies

log = logging.getLogger("viddown.pages")

FB_STORY = re.compile(r"^https?://(?:www\.|m\.|web\.|mbasic\.)?facebook\.com/stories/", re.I)
# tlačítko, které Facebook zobrazí před přehráním story (česky / anglicky)
GATE_TEXT = re.compile(r"zobraz\S*\s+se\s+p\S+|zobrazit\s+p\S+|click\s+to\s+view|view\s+story|tap\s+to\s+view", re.I)
LINKS_JS = "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
VIDEO_JS = "() => Array.from(document.querySelectorAll('video')).map(v => ({h: v.videoHeight, w: v.videoWidth, d: v.duration}))"
# řádek s autorem je těsně před stářím příspěvku („15 h“, „20 min“, „2 d“)
AGE = re.compile(r"^\d+\s?(?:s|m|min|h|hod|d|dn|dní|w|t)\.?$", re.I)
TEXT_JS = "() => document.body.innerText"

_REEL = re.compile(r"facebook\.com/reel/(\d+)", re.I)
_OTHER = re.compile(r"facebook\.com/(?:watch/?\?(?:[^#]*&)?v=\d+|[^/?#]+/videos/(?:[^/?#]+/)?\d+|video\.php\?(?:[^#]*&)?v=\d+)", re.I)


def is_story_url(url: str) -> bool:
    return bool(FB_STORY.match(url or ""))


def pick_video_link(hrefs: list[str]) -> str | None:
    """Z odkazů na stránce vybere první odkaz na reel nebo video (reel s čistou adresou bez sledovacích parametrů)."""
    for h in hrefs:
        m = _REEL.search(h)
        if m:
            return f"https://www.facebook.com/reel/{m.group(1)}/"
    for h in hrefs:
        if _OTHER.search(h):
            return h
    return None


def whole_file_url(url: str) -> str:
    """Adresa celého souboru: bez parametrů bytestart/byteend, kterými přehrávač žádá jen kousky."""
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in ("bytestart", "byteend")]
    return p._replace(query=urlencode(q)).geturl()


def stream_kind(url: str) -> str:
    """„audio“ nebo „video“ podle parametru efg (base64 JSON s vencode_tag, např. …_audio)."""
    efg = dict(parse_qsl(urlparse(url).query)).get("efg", "")
    try:
        tag = json.loads(base64.urlsafe_b64decode(efg + "=" * (-len(efg) % 4))).get("vencode_tag", "")
    except Exception:  # noqa: BLE001
        tag = ""
    return "audio" if "audio" in tag.lower() else "video"


def story_author(text: str) -> str | None:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if i > 0 and AGE.match(l):
            return lines[i - 1][:80]
    return None


async def open_story(url: str, ctx) -> dict:
    try:
        from playwright.async_api import TimeoutError as PWTimeout
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise ResolveError(f"Playwright není nainstalován: {e}", "engine")
    s = ctx.settings
    timeout = float(s.get("sniff_timeout", 40))
    media: dict[str, str] = {}   # celý soubor -> "audio" | "video"
    async with async_playwright() as p:
        kw = {"headless": True}
        if s.get("proxy"):
            kw["proxy"] = {"server": s["proxy"]}
        try:
            browser = await p.chromium.launch(**kw)
        except Exception as e:  # noqa: BLE001
            raise ResolveError(f"Chromium nelze spustit ({e}). Nainstalujte ho v Enginy.", "engine")
        try:
            context = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720}, locale="cs-CZ")
            cookies = []
            if ctx.cookies_file:
                await add_cookies(context, ctx.cookies_file)
            page = await context.new_page()

            def on_response(resp):
                try:
                    ct = (resp.headers.get("content-type") or "").lower()
                    if ct.startswith("video/") and resp.status in (200, 206):
                        media.setdefault(whole_file_url(resp.url), stream_kind(resp.url))
                except Exception:  # noqa: BLE001
                    pass
            page.on("response", on_response)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            except PWTimeout:
                pass
            except Exception as e:  # noqa: BLE001
                raise ResolveError(f"stránku nelze načíst: {str(e).splitlines()[0]}", "network")
            start = time.monotonic()
            last_click = 0.0
            link = None
            while time.monotonic() - start < min(timeout, 30):
                await page.wait_for_timeout(1000)
                if time.monotonic() - start > 2.5 and time.monotonic() - last_click > 3:
                    # před přehráním Facebook chce klik („Klikněte a zobrazí se příběh“). Stránka se často
                    # ještě „oživuje“ a první klik se ztratí, proto se klikání opakuje, dokud text nezmizí.
                    try:
                        gate = page.get_by_text(GATE_TEXT)
                        if await gate.count():
                            last_click = time.monotonic()
                            await gate.first.click(timeout=5000)
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    link = pick_video_link(await page.evaluate(LINKS_JS))
                except Exception:  # noqa: BLE001
                    link = None
                if link:
                    break
                # vlastní video story: oba proudy (obraz i zvuk) se načetly (zvuk nemusí být vůbec)
                if "video" in media.values() and time.monotonic() - start > 6:
                    break
            if link:
                log.info("story %s odkazuje na %s", url, link)
                return {"link": link}
            if "video" in media.values():
                vids = [u for u, k in media.items() if k == "video"]
                auds = [u for u, k in media.items() if k == "audio"]
                try:
                    info = (await page.evaluate(VIDEO_JS) or [{}])[0]
                    author = story_author(await page.evaluate(TEXT_JS))
                    cookies = await context.cookies()
                except Exception:  # noqa: BLE001
                    info, author = {}, None
                cand = {"kind": "direct", "url": vids[0], "audio": auds[0] if auds else None,
                        "height": int(info.get("h") or 0) or None, "duration": info.get("d") or None, "rank": 3}
                log.info("story %s má vlastní video (%s)", url, cand["height"])
                return {"sniff": {"title": f"{author} – story" if author else "Facebook story", "thumbnail": None,
                                  "candidates": [cand], "drm": False, "referer": "https://www.facebook.com/",
                                  "cookies": cookies}}
            login = "login" in page.url or await page.locator("input[name=pass]").count() > 0
            if login:
                raise ResolveError("Facebook vyžaduje přihlášení – nahrajte cookies.txt z přihlášeného prohlížeče", "login")
            raise ResolveError("story neobsahuje video ani odkaz na reel (fotky ze Stories se nestahují)", "unsupported")
        finally:
            await browser.close()
