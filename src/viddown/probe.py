"""Kontrola URL (probe): kolik videí URL obsahuje, rozlišení prvního, miniatura, název.

Běží pro každou nově přidanou položku v samostatném vlákně (asyncio úloze) mimo sloty stahování.
"""
from __future__ import annotations

import asyncio
import logging
import time

from . import nested
from .resolvers import Ctx, ResolveError
from .resolvers import k2s, pages, sniffer, ytdlp
from .util import url_list_name, domain, fallback_allowed, youtube_channel_base

log = logging.getLogger("viddown.probe")

KEEP = ("id", "title", "channel", "uploader", "upload_date", "height", "duration", "thumbnail", "extractor_key",
        "webpage_url", "is_live", "live_status", "playlist_title", "playlist_index", "filesize_approx", "age_limit")


def trim_info(info: dict) -> dict:
    out = {k: info.get(k) for k in KEEP if info.get(k) is not None}
    rf = info.get("requested_formats")
    if rf:
        out["requested_formats"] = [{k: f.get(k) for k in ("format_id", "filesize", "filesize_approx", "height")} for f in rf]
    elif info.get("format_id"):
        out["requested_formats"] = [{k: info.get(k) for k in ("format_id", "filesize", "filesize_approx", "height")}]
    out["full"] = True
    return out


def _thumb(e: dict) -> str | None:
    th = e.get("thumbnails")
    if th:
        # největší dostupná (poslední bývá největší)
        th = [t for t in th if t.get("url")]
        if th:
            return th[-1]["url"]
    return e.get("thumbnail")


def _entry_url(e: dict) -> str | None:
    u = e.get("url") or e.get("webpage_url")
    if u and u.startswith("http"):
        return u
    if e.get("ie_key") == "Youtube" and e.get("id"):
        return f"https://www.youtube.com/watch?v={e['id']}"
    return u


def _flatten(entries) -> list[dict]:
    out = []
    for e in entries or []:
        if not e:
            continue
        if e.get("_type") == "playlist" and e.get("entries"):
            out += _flatten(e["entries"])
            continue
        if nested.is_list_entry(e):                                   # odkaz na další playlist, ne video (viz nested.py)
            continue
        u = _entry_url(e)
        if not u:
            continue
        out.append({"url": u, "title": e.get("title"), "thumb_url": _thumb(e), "duration": e.get("duration"),
                    "channel": e.get("channel") or e.get("uploader"), "id": e.get("id"),
                    "upload_date": e.get("upload_date"), "timestamp": e.get("timestamp"),
                    "live_status": e.get("live_status")})
    return out


def _entries_channel(entries: list[dict]) -> str | None:
    """Autor, který je u všech položek stejný (stránky bez vlastního názvu seznamu)."""
    names = {e.get("channel") for e in entries if e.get("channel")}
    return names.pop() if len(names) == 1 else None


async def _probe_ytdlp(url: str, ctx: Ctx) -> dict:
    base = youtube_channel_base(url)
    s = ctx.settings
    if base:
        tabs = s.get("channel_tabs") or ["videos"]
        entries, title, thumb = [], None, None
        first_err = None
        for tab in tabs:
            try:
                info = await ytdlp.probe(f"{base}/{tab}", ctx)
            except ResolveError as e:
                first_err = first_err or e
                continue
            title = title or info.get("channel") or info.get("uploader") or (info.get("title") or "").split(" - ")[0]
            thumb = thumb or _thumb(info)
            entries += _flatten(info.get("entries"))
        if not entries and first_err:
            raise first_err
        return await _list_result("channel", title or domain(url), thumb, entries, ctx)

    info = await ytdlp.probe(url, ctx)
    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        entries = _flatten(info.get("entries"))
        if not entries:                                                # např. záložka „Playlisty“: videa všech playlistů, každý do své podsložky
            entries = await _expand_lists(nested.list_infos(info.get("entries")), ctx)
        is_channel = bool(info.get("channel_id") and info.get("id") == info.get("channel_id"))
        slug, slug_channel = url_list_name(url)
        is_channel = is_channel or slug_channel
        title = (info.get("title") or info.get("channel") or info.get("uploader") or _entries_channel(entries)
                 or slug or domain(url))
        return await _list_result("channel" if is_channel else "playlist", title, _thumb(info), entries, ctx)

    if s.get("quality") == "compat" or s.get("audio_only"):
        try:
            info = await ytdlp.full_info(url, ctx)
        except ResolveError:
            pass
    ti = trim_info(info)
    return {"type": "video", "method": "ytdlp", "title": info.get("title"), "thumb_url": _thumb(info),
            "height": ytdlp.best_height(info), "count": 1, "approx": False, "info": ti,
            "duration": info.get("duration"), "channel": info.get("channel") or info.get("uploader"),
            "size_est": ytdlp.size_estimate(info), "live": bool(info.get("is_live"))}


async def _expand_lists(lists: list[dict], ctx: Ctx) -> list[dict]:
    """Videa ze seznamu playlistů (nejvýš `nested.MAX_LISTS`, po třech najednou). Každé video nese `group` = název playlistu
    (podsložka při stahování). Playlist, který se nepodaří načíst, se přeskočí; stejné video ve více playlistech se bere jednou."""
    lists = lists[:nested.MAX_LISTS]
    sem = asyncio.Semaphore(3)

    async def one(item: dict) -> list[dict]:
        async with sem:
            try:
                info = await ytdlp.probe(item["url"], ctx)
            except ResolveError as e:
                log.info("playlist %s nelze načíst: %s", item["url"], e)
                return []
        group = item.get("title") or info.get("title") or "playlist"
        es = _flatten(info.get("entries"))
        for e in es:
            e["group"] = group
        return es

    out, seen = [], set()
    for es in await asyncio.gather(*(one(i) for i in lists)):
        for e in es:
            if e["url"] not in seen:
                seen.add(e["url"])
                out.append(e)
    return out


async def _list_result(kind: str, title: str, thumb: str | None, entries: list[dict], ctx: Ctx) -> dict:
    if not entries:
        raise ResolveError("playlist je prázdný", "unsupported")
    height = None
    try:
        first = await ytdlp.full_info(entries[0]["url"], ctx, timeout=120)
        height = ytdlp.best_height(first)
        entries[0]["info"] = trim_info(first)
    except ResolveError as e:
        log.info("rozlišení prvního videa nezjištěno: %s", e)
    return {"type": kind, "method": "ytdlp", "title": title, "thumb_url": thumb or entries[0].get("thumb_url"),
            "height": height, "count": len(entries), "approx": False, "entries": entries,
            "channel": entries[0].get("channel")}


async def _probe_sniffer(url: str, ctx: Ctx) -> dict:
    return _sniff_result(await sniffer.sniff(url, ctx), url)


def _sniff_result(sn: dict, url: str) -> dict:
    cands = sn["candidates"]
    if not cands:
        if sn["drm"]:
            raise ResolveError("video je chráněné DRM", "drm")
        raise ResolveError("na stránce nebylo nalezeno žádné video", "unsupported")
    streams = [c for c in cands if c["kind"] != "direct"]
    count = len(streams) or len(cands)
    best = cands[0]
    return {"type": "video", "method": "sniffer", "title": sn["title"] or domain(url), "thumb_url": sn["thumbnail"],
            "height": best.get("height"), "count": count, "approx": True,
            "info": {"sniff": sn, "sniffed_at": time.time(), "title": sn["title"]},
            "duration": best.get("duration"), "channel": domain(url), "size_est": best.get("len") or None,
            "live": False, "drm": sn["drm"]}


async def probe_url(url: str, ctx: Ctx) -> dict:
    """Projde metody podle nastaveného pořadí. Na další metodu přejde jen když video nebylo nalezeno."""
    if k2s.file_id_of(url) and ctx.settings.get("k2s_enabled", True):
        # Keep2Share: o dostupnosti souboru rozhodne až API při stahování (odpočet, captcha), tady se jen zařadí
        from pathlib import PurePosixPath
        from urllib.parse import unquote, urlparse
        name = PurePosixPath(unquote(urlparse(url).path)).name or None
        return {"type": "video", "title": name, "info": {}, "method": "k2s"}
    if pages.is_story_url(url):
        # Facebook Story: video leží za odkazem (sdílený reel) – najdeme ho a zkontrolujeme jako běžné video
        try:
            st = await pages.open_story(url, ctx)
            if "sniff" in st:  # story má vlastní video (ne sdílený reel): stahuje ho prohlížeč, takže platí nastavení metod
                if "sniffer" not in (ctx.settings.get("methods") or ["ytdlp", "sniffer"]):
                    return {"type": "none", "error": "video příběhu se dá stáhnout jen prohlížečem a metoda Prohlížeč je vypnutá",
                            "error_kind": "unsupported"}
                return _sniff_result(st["sniff"], url)
        except ResolveError as e:
            log.info("probe %s (story): %s (%s)", url, e, e.kind)
            return {"type": "none", "error": str(e), "error_kind": e.kind}
        target = st["link"]
        res = await probe_url(target, ctx)
        if res.get("type") != "none":
            res["resolved_url"] = target
            if isinstance(res.get("info"), dict):
                res["info"]["origin_url"] = url
        return res
    errors: list[ResolveError] = []
    for m in ctx.settings.get("methods") or ["ytdlp", "sniffer"]:
        try:
            if m == "ytdlp":
                return await _probe_ytdlp(url, ctx)
            if m == "sniffer":
                return await _probe_sniffer(url, ctx)
        except ResolveError as e:
            log.info("probe %s přes %s: %s (%s)", url, m, e, e.kind)
            errors.append(e)
            if not fallback_allowed(e.kind):
                break
    last = errors[-1] if errors else ResolveError("žádná metoda", "other")
    # u snifferu je chyba "nenalezeno" obecnější než chyba yt-dlp "unsupported url"
    return {"type": "none", "error": str(last), "error_kind": last.kind}
