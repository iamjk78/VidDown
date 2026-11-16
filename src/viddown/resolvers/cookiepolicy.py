"""Cookies jen když je potřeba (nastavení `cookies_use`).

- „always“ (výchozí): cookies se posílají vždy, jako ve starších verzích.
- „needed“: nejdřív se zkusí bez cookies. Když web ohlásí, že chce přihlášení (věk, „nejste robot“, jen pro členy…),
  zkusí se to hned znovu s cookies a web si aplikace zapamatuje na `LEARN_DAYS` dní (pak chodí rovnou s cookies).
  Weby z `cookies_always_hosts` dostávají cookies vždy – hodí se u webů, které bez přihlášení tiše vrátí horší kvalitu
  nebo neúplný seznam videí (tam žádná chyba nepřijde a poznat se to nedá).

Omezení webu (HTTP 429) ani chyby sítě opakování s cookies nespouštějí.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from ..util import host_key, is_rate_limited
from . import Ctx, ResolveError

log = logging.getLogger("viddown.cookies")

LEARN_DAYS = 7
FILE = "cookie_hosts.json"
MAX_HOSTS = 500
_lock = threading.Lock()


def needed_mode(settings: dict) -> bool:
    return settings.get("cookies_use", "always") == "needed"


def available(ctx: Ctx) -> bool:
    """Má aplikace vůbec nějaké cookies k použití?"""
    mode = ctx.settings.get("cookies_mode")
    if mode == "browser":
        return True
    return mode == "file" and (ctx.data / "cookies.txt").exists()


def norm_host(text: str) -> str:
    """„https://www.Example.com/cesta“ → „example.com“."""
    t = (text or "").strip().lower()
    if "://" in t:
        t = urlparse(t).netloc
    t = t.split("/")[0].split("@")[-1].split(":")[0].strip(".")
    return t.removeprefix("www.")


def parse_hosts(text: str) -> list[str]:
    out = []
    for part in re.split(r"[\s,;]+", text or ""):
        h = norm_host(part)
        if h and re.fullmatch(r"[a-z0-9.-]+", h) and h not in out:
            out.append(h)
    return out


def _matches(host: str, dom: str) -> bool:
    return host == dom or host.endswith("." + dom)


def _host(url: str) -> str:
    return host_key(url)


# --- naučené weby ------------------------------------------------------------------------------------------------------
def _path(data: Path) -> Path:
    return Path(data) / FILE


def _read(data: Path) -> dict[str, float]:
    try:
        d = json.loads(_path(data).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    now = time.time()
    out = {}
    for h, until in d.items():
        try:
            if isinstance(h, str) and float(until) > now:
                out[h] = float(until)
        except (TypeError, ValueError):
            continue
    return out


def _write(data: Path, d: dict[str, float]) -> None:
    p = _path(data)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    os.replace(tmp, p)


def learned(data: Path) -> dict[str, float]:
    """Weby, které si aplikace zapamatovala ({web: platí do})."""
    with _lock:
        return _read(data)


def learn(data: Path, url: str) -> None:
    h = _host(url)
    if not h:
        return
    with _lock:
        d = _read(data)
        d[h] = time.time() + LEARN_DAYS * 86400
        if len(d) > MAX_HOSTS:                                             # nejdřív vyprší ty nejstarší
            d = dict(sorted(d.items(), key=lambda kv: kv[1])[-MAX_HOSTS:])
        try:
            _write(data, d)
        except OSError as e:
            log.warning("nelze uložit seznam webů s cookies: %s", e)


def forget(data: Path, host: str) -> None:
    with _lock:
        d = _read(data)
        if d.pop(norm_host(host), None) is not None or d.pop(host, None) is not None:
            _write(data, d)


# --- rozhodnutí ----------------------------------------------------------------------------------------------------------
def wanted(ctx: Ctx, url: str) -> bool:
    """Mají se cookies pro tuto adresu poslat hned v prvním pokusu?"""
    if not needed_mode(ctx.settings):
        return True
    h = _host(url)
    if not h:
        return True
    if any(_matches(h, d) or _matches(d, h) for d in parse_hosts(ctx.settings.get("cookies_always_hosts", ""))):
        return True
    return any(_matches(h, d) for d in learned(ctx.data))


def is_login(e: ResolveError) -> bool:
    return e.kind == "login" and not is_rate_limited(str(e))


def file_has_host(ctx: Ctx, url: str) -> bool:
    """Obsahuje cookies.txt přihlášení právě k tomuto webu? (prohlížeč ve snifferu čte jen soubor)"""
    p = ctx.data / "cookies.txt"
    if ctx.settings.get("cookies_mode") != "file" or not p.exists():
        return False
    from .sniffer import cookie_applies, parse_netscape_cookies
    host = (urlparse(url).hostname or "").lower()
    try:
        return any(cookie_applies(c["domain"], host) for c in parse_netscape_cookies(p))
    except OSError:
        return False


def with_cookies(ctx: Ctx) -> Ctx:
    return dataclasses.replace(ctx, no_cookies=False)


def without_cookies(ctx: Ctx) -> Ctx:
    return dataclasses.replace(ctx, no_cookies=True)


async def attempt(ctx: Ctx, url: str, fn, empty=None):
    """Zavolá `fn(ctx)` podle pravidla cookies. `empty(výsledek)` = True znamená „nic nenalezeno“ (sniffer): pak se při
    cookies pro tento web zkusí jednou znovu s nimi."""
    if ctx.no_cookies is not None:                                         # už rozhodnuto výš (vnořené volání)
        return await fn(ctx)
    if not available(ctx) or wanted(ctx, url):
        return await fn(with_cookies(ctx))
    host = _host(url)
    try:
        res = await fn(without_cookies(ctx))
    except ResolveError as e:
        if not is_login(e):
            raise
        log.info("%s: bez cookies to nejde (%s), zkouším s cookies", host, str(e)[:160])
        res = await fn(with_cookies(ctx))
        learn(ctx.data, url)
        log.info("%s: s cookies to šlo, web si pamatuji na %d dní", host, LEARN_DAYS)
        return res
    if empty is not None and empty(res) and file_has_host(ctx, url):
        log.info("%s: bez cookies se na stránce nic nenašlo, zkouším s cookies", host)
        try:
            res2 = await fn(with_cookies(ctx))
        except ResolveError:
            return res
        if not empty(res2):
            learn(ctx.data, url)
            log.info("%s: s cookies to šlo, web si pamatuji na %d dní", host, LEARN_DAYS)
            return res2
    return res
