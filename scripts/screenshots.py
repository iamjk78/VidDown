#!/usr/bin/env python3
"""Snímky obrazovky do README (docs/img/) z ukázkových dat (scripts/demo_data.py --serve). Česky i anglicky, světlý motiv.

    VIDDOWN_DOCKER=1 VIDDOWN_PASSWORD=ukazka .venv/bin/python scripts/demo_data.py /tmp/vd-demo --lang cs --serve &   (pak --lang en)
    .venv/bin/python scripts/screenshots.py http://127.0.0.1:8798 cs
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "img"


async def main(base: str, langs: list[str]) -> None:
    from playwright.async_api import async_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for lang in langs:
            ctx = await b.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1, color_scheme="light", locale=lang)
            page = await ctx.new_page()
            await page.goto(base + "/#queue")
            await page.wait_for_timeout(1500)
            if await page.query_selector("input[type=password]"):                # ukázkový server s heslem (VIDDOWN_PASSWORD=ukazka)
                await page.screenshot(path=str(OUT / f"prihlaseni-{lang}.png"))
                await page.fill("input[type=password]", "ukazka")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1500)

            async def shot(name: str, hash_: str | None = None, wait: int = 1500, full: bool = False):
                if hash_ is not None:
                    await page.evaluate(f"location.hash = '{hash_}'")
                    await page.wait_for_timeout(wait)
                await page.screenshot(path=str(OUT / f"{name}-{lang}.png"), full_page=full)

            await shot("fronta", "#queue")
            await shot("katalog", "#catalog", 2500)
            await shot("nastaveni", "#settings")
            # průvodce prvním spuštěním: krok „Kam ukládat videa“ a závěrečné shrnutí
            await page.evaluate("location.hash = '#queue'")
            await page.wait_for_timeout(800)
            await page.evaluate("openWizard()")
            await page.wait_for_timeout(500)
            await page.click("#wnext")
            await page.wait_for_timeout(600)
            await shot("pruvodce-slozka")
            for _ in range(4):
                await page.click("#wnext")
                await page.wait_for_timeout(500)
            await shot("pruvodce-hotovo")
            await ctx.close()
        await b.close()
    print("Hotovo:", sorted(x.name for x in OUT.glob("*.png")))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8798", sys.argv[2:] or ["cs"]))
