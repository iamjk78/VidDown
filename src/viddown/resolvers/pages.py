"""Stránky, které video neobsahují přímo, ale odkazují na něj (např. Facebook Stories se sdíleným reelem).

resolve_embedded() otevře stránku v prohlížeči (s cookies), odklikne „zobrazit příběh“ a vrátí URL
videa, na které story odkazuje. To pak stáhne yt-dlp jako každé jiné video.
"""
from __future__ import annotations

import logging
import re
import time

from . import ResolveError
from .sniffer import UA, add_cookies

log = logging.getLogger("viddown.pages")

FB_STORY = re.compile(r"^https?://(?:www\.|m\.|web\.|mbasic\.)?facebook\.com/stories/", re.I)
# tlačítko, které Facebook zobrazí před přehráním story (česky / anglicky)
GATE_TEXT = re.compile(r"zobraz\S*\s+se\s+p\S+|zobrazit\s+p\S+|click\s+to\s+view|view\s+story|tap\s+to\s+view", re.I)
LINKS_JS = "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"

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


async def resolve_embedded(url: str, ctx) -> str:
    """Vrátí URL videa, na které story odkazuje. ResolveError, když tam žádné není."""
    try:
        from playwright.async_api import TimeoutError as PWTimeout
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise ResolveError(f"Playwright není nainstalován: {e}", "engine")
    s = ctx.settings
    timeout = float(s.get("sniff_timeout", 40))
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
            if ctx.cookies_file:
                await add_cookies(context, ctx.cookies_file)
            page = await context.new_page()
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
            if not link:
                login = "login" in page.url or await page.locator("input[name=pass]").count() > 0
                if login:
                    raise ResolveError("Facebook vyžaduje přihlášení – nahrajte cookies.txt z přihlášeného prohlížeče", "login")
                raise ResolveError("story neobsahuje odkaz na reel ani video (vlastní video Story zatím nelze stáhnout)", "unsupported")
            log.info("story %s odkazuje na %s", url, link)
            return link
        finally:
            await browser.close()
