"""Odběry: pravidelná kontrola kanálů a playlistů. Nová videa se řadí do běžné fronty.

Pravidla:
- kontroluje se od nejnovějších videí; u kanálu se čtení zastaví u prvního videa staršího než „od data“
  (videa na kanálu jsou řazena od nejnovějšího), u playlistu se projdou všechna;
- přeskakují se videa, která už jsou v archivu stažených (archive.txt), videa, ze kterých už pro odběr vznikla úloha,
  a živá vysílání / premiéry (zkusí se při další kontrole, až skončí);
- první kontrola (nebo prázdný odběr) s víc videi, než je práh potvrzení, nic nezařadí a počká na potvrzení.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time

from . import pagelist
from .probe import _flatten
from .resolvers import ResolveError, ytdlp
from .util import is_rate_limited, youtube_channel_base

log = logging.getLogger("viddown.subscriptions")

FIRST_RUN_LIMIT = 500      # nejvýše tolik nejnovějších videí se vyhodnotí při první kontrole
REGULAR_LIMIT = 60         # a při dalších kontrolách
MAX_FETCH_PER_RUN = 40     # kolik videí bez data se za jednu kontrolu dohledá (plné info je pomalé)
SEEN_OLD_CAP = 3000
LIVE = ("is_live", "is_upcoming", "post_live")


# ------------------------------------------------------------ pomocné funkce
def today() -> str:
    return dt.date.today().isoformat()


def parse_since(value) -> str | None:
    """'now' → dnes, 'month' → před měsícem, 'all'/prázdné → bez omezení, jinak datum YYYY-MM-DD."""
    if value in (None, "", "all"):
        return None
    if value == "now":
        return today()
    if value == "month":
        d = dt.date.today()
        y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
        for day in (d.day, 28):
            try:
                return dt.date(y, m, day).isoformat()
            except ValueError:
                continue
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValueError(f"neplatné datum: {value} (očekává se RRRR-MM-DD)")


def entry_date(e: dict) -> str | None:
    if e.get("date") and len(str(e["date"])) == 10:     # datum z textu odkazu (odběr ze stránky)
        return str(e["date"])
    ud = e.get("upload_date")
    if ud and len(str(ud)) == 8 and str(ud).isdigit():
        return f"{ud[:4]}-{ud[4:6]}-{ud[6:]}"
    ts = e.get("timestamp")
    if ts:
        try:
            return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).date().isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    return None


def archive_ids(data_dir) -> set[str]:
    """ID videí z archive.txt (řádky „extractor id“)."""
    p = data_dir / "archive.txt"
    if not p.exists():
        return set()
    return {l.split(" ", 1)[-1].strip() for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()}


CHECK_CHOICES = (3, 6, 12, 24, 72, 168, 720)    # hodiny: 3 h, 6 h, 12 h, 1 den, 3 dny, 1 týden, 1 měsíc


def interval_hours(sub: dict, default: float) -> float:
    """Interval kontroly odběru: vlastní, jinak globální (0 = nekontrolovat)."""
    return float(sub["check_hours"]) if sub.get("check_hours") else float(default or 0)


def due(db, hours: float, now: float | None = None, skip=None) -> dict | None:
    """Nejdřív na řadě zapnutý odběr, který nečeká na potvrzení a naposledy se kontroloval před víc než jeho interval
    (vlastní, jinak globální `hours`; 0 = nekontrolovat). `skip(url)` vyřadí odběry pozastavených webů (ostatní se kontrolují dál)."""
    now = now or time.time()
    best = None
    for s in db.sub_list():
        if not s["enabled"] or s["pending"]:
            continue
        if skip is not None and skip(s["url"]):
            continue
        h = interval_hours(s, hours)
        if h <= 0:
            continue
        last = s["last_check"]
        if last is not None and now - last < h * 3600:
            continue
        if best is None or (last or 0) < (best["last_check"] or 0):
            best = s
    return best


async def list_sources(sub: dict, ctx, limit: int) -> list[list[dict]]:
    """Seznamy videí odběru od nejnovějších; u kanálu jeden seznam na záložku (videa / shorts / živě)."""
    url = sub["url"]
    if sub["kind"] == "page":
        pages = 60 if sub["last_check"] is None else 3
        try:
            return [await pagelist.list_items(sub, ctx, pages, sub["since"])]
        except pagelist.PageError as e:
            raise ResolveError(str(e), "other") from e
    base = youtube_channel_base(url) if sub["kind"] == "channel" else None
    if not base:
        info = await ytdlp.probe(url, ctx, playlist_end=limit)
        return [_flatten(info.get("entries"))]
    tabs = json.loads(sub["tabs"]) if sub["tabs"] else (ctx.settings.get("channel_tabs") or ["videos"])
    out, first_err = [], None
    for tab in tabs:
        try:
            info = await ytdlp.probe(f"{base}/{tab}", ctx, playlist_end=limit)
        except ResolveError as e:
            first_err = first_err or e
            continue
        out.append(_flatten(info.get("entries")))
    if not out and first_err:
        raise first_err
    return out


# ------------------------------------------------------------ kontrola
async def check(runner, sid: int) -> dict:
    """Zkontroluje odběr. Vrací {"queued": n, "pending": n, "error": text}."""
    db = runner.db
    sub = db.sub_get(sid)
    if not sub:
        return {"error": "odběr neexistuje"}
    ctx = runner.ctx()
    first = sub["last_check"] is None
    threshold = int(ctx.settings.get("playlist_confirm_threshold", 50))
    now = time.time()
    try:
        sources = await list_sources(sub, ctx, FIRST_RUN_LIMIT if first else REGULAR_LIMIT)
    except ResolveError as e:
        log.info("odběr %s: kontrola selhala: %s", sid, e)
        db.sub_update(sid, last_check=now, last_error=str(e))
        if is_rate_limited(str(e)):                                  # omezení webu platí i pro frontu a ostatní odběry téhož webu
            runner.note_host_limit(sub["url"], str(e))
        if e.kind == "cookies":
            runner._pause_for_cookies(str(e))
        return {"error": str(e)}

    since = sub["since"]
    seen_old = dict.fromkeys(json.loads(sub["seen_old"] or "[]"))          # slovník kvůli pořadí: při překročení limitu se zahodí nejstarší, ne abecedně první
    known = archive_ids(runner.data) | {r["url"] for r in db.query("select url from jobs where sub_id=?", (sid,))}
    is_channel = sub["kind"] == "channel"
    new: list[dict] = []
    fetched = 0
    for entries in sources:
        for e in entries:
            vid = str(e.get("id") or e["url"])
            if vid in known or e["url"] in known or any(x["url"] == e["url"] for x in new):
                continue
            if vid in seen_old:
                if is_channel:
                    break      # od nejnovějších: dál už jsou jen starší videa
                continue
            if e.get("live_status") in LIVE:
                continue
            d = entry_date(e)
            if d is None and since and fetched < MAX_FETCH_PER_RUN:
                fetched += 1
                try:
                    info = await ytdlp.full_info(e["url"], ctx, timeout=120)
                except ResolveError as err:
                    log.info("odběr %s: %s: %s", sid, e["url"], err)
                    continue
                if info.get("is_live") or info.get("live_status") in LIVE:
                    continue
                d = entry_date(info)
                e["title"] = e.get("title") or info.get("title")
                e["thumb_url"] = e.get("thumb_url") or info.get("thumbnail")
                e["duration"] = e.get("duration") or info.get("duration")
                e["channel"] = e.get("channel") or info.get("channel") or info.get("uploader")
            if since and d is None and sub["kind"] != "page":              # datum neznámé (limit dotazů nebo chyba): nezařazovat, zkusí se příště
                continue
            if since and d and d < since:
                seen_old[vid] = None
                if is_channel:
                    break
                continue
            e["date"] = d
            new.append(e)

    if sub["kind"] == "page":      # už zařazené díly se znovu nenabídnou, ani když se záznam z historie smaže
        seen_old.update(dict.fromkeys(str(e.get("id") or e["url"]) for e in new))
    seen_json = json.dumps(list(seen_old)[-SEEN_OLD_CAP:])
    if first and len(new) > threshold:
        pending = [{k: e.get(k) for k in ("url", "id", "title", "thumb_url", "duration", "channel", "date")} for e in new]
        db.sub_update(sid, last_check=now, last_error=None, seen_old=seen_json, pending=pending)
        log.info("odběr %s: nalezeno %d videí, čeká na potvrzení", sid, len(new))
        return {"queued": 0, "pending": len(new)}
    n = queue_entries(db, sub, new)
    db.sub_update(sid, last_check=now, last_error=None, seen_old=seen_json)
    if n:
        log.info("odběr %s (%s): do fronty přidáno %d videí", sid, sub["title"] or sub["url"], n)
    return {"queued": n, "pending": 0}


def queue_entries(db, sub: dict, entries: list[dict]) -> int:
    """Zařadí videa do fronty (v pořadí od nejnovějšího). Bez dalšího potvrzování."""
    n = 0
    active = db.active_urls()                                       # video, které už je ve frontě (ručně nebo z jiného odběru), se nepřidá znovu
    for e in entries:
        if e["url"] in active:
            continue
        active.add(e["url"])
        db.add(e["url"], source="subscription", status="queued", kind="video", title=e.get("title"),
               thumb_url=e.get("thumb_url"), channel=e.get("channel") or sub.get("title"), duration=e.get("duration"),
               sub_id=sub["id"], target_dir=sub["folder"], auto_confirm=1,
               info={"id": e.get("id"), "title": e.get("title"), "upload_date": e.get("date")})
        n += 1
    return n


def confirm_pending(db, sid: int) -> int:
    sub = db.sub_get(sid)
    if not sub or not sub["pending"]:
        return 0
    n = queue_entries(db, sub, json.loads(sub["pending"]))
    db.sub_update(sid, pending=None)
    return n


def reject_pending(db, sid: int) -> int:
    """Čekající videa se zahodí (už se nenabídnou): přidají se mezi „starší“ videa odběru."""
    sub = db.sub_get(sid)
    if not sub or not sub["pending"]:
        return 0
    items = json.loads(sub["pending"])
    seen = dict.fromkeys(json.loads(sub["seen_old"] or "[]"))
    seen.update(dict.fromkeys(str(i.get("id") or i["url"]) for i in items))
    db.sub_update(sid, pending=None, seen_old=list(seen)[-SEEN_OLD_CAP:])
    return len(items)
