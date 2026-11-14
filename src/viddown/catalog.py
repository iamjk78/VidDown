"""Katalog (PLAN.md kap. 20): zdroje (kanály, playlisty, videa) se jen prozkoumají a videa z nich se nabízejí k výběru.

Etapa 1: přidání zdrojů, vlastní fronta zjišťování, seznam videí zdroje, „staženo dříve“, dotazy na položky
(filtry, řazení, stránkování). Podrobnosti (rozlišení, velikost), miniatury, tlačítka stáhnout/odstranit a další typy
zdrojů přijdou v dalších etapách.

Stavy položky: `new` a `queued` jsou vidět; `removed` (odstraněno uživatelem), `done` (staženo) a `gone` (nedostupné
nebo ze zdroje zmizelo) se pamatují a skrývají. Běžné obnovení zdroje (`scan_mode=new`) přidá jen dosud nenabídnutá
videa; „načíst znovu vše“ (`scan_mode=all`) nabídne znovu i odmítnutá (odznak `rejected_before`) a stažená
(`downloaded_before`). Stejně se chová opětovné přidání adresy, která už v katalogu je. Odebrání zdroje smaže i paměť.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import schedule
from . import pagelist, storyboard
from .resolvers import ResolveError, sniffer, ytdlp
from . import nested
from .util import domain, sanitize_filename, url_list_name, youtube_channel_base

log = logging.getLogger("viddown.catalog")

LIST_TIMEOUT = 3600           # načtení seznamu velkého kanálu může trvat dlouho
MAX_URLS = 2000
BLOCKED_RE = re.compile(r"HTTP (401|403|406|410|451)\b")        # odpovědi, kdy web odmítá program, ale prohlížeč nejspíš pustí
MAX_QUERY_TOKENS = 10
MAX_QUERY_CHARS = 200
MAX_OFFSET = 10_000_000
MAX_SELECT = 200_000
DL_NOTE = "stahování"                 # poznámky o neúspěšném stažení začínají tímto slovem (ukládají se do detail_error)
ACTIVE_JOB = ("new", "probing", "confirm", "queued", "running", "cancelling", "expanded")
THUMB_ALTS_MAX = 9
UNAVAILABLE_TITLES = ("[private video]", "[deleted video]")

# Délka videa v sekundách: navazující intervaly (horní mez včetně), „over“ je nad hodinu, „unknown“ bez zjištěné délky.
DUR_BUCKETS = {
    "20": "i.duration <= 20",
    "60": "i.duration > 20 and i.duration <= 60",
    "120": "i.duration > 60 and i.duration <= 120",
    "300": "i.duration > 120 and i.duration <= 300",
    "600": "i.duration > 300 and i.duration <= 600",
    "1800": "i.duration > 600 and i.duration <= 1800",
    "3600": "i.duration > 1800 and i.duration <= 3600",
    "over": "i.duration > 3600",
    "unknown": "i.duration is null",
}

# Rozlišení podle nejbližší běžné hodnoty (výška obrazu).
RES_BUCKETS = {
    "2160": "i.height >= 2000",
    "1440": "i.height >= 1300 and i.height < 2000",
    "1080": "i.height >= 1000 and i.height < 1300",
    "720": "i.height >= 700 and i.height < 1000",
    "480": "i.height >= 460 and i.height < 700",
    "360": "i.height < 460",
    "unknown": "i.height is null",
}
SORT_COLUMNS = {"height": "height", "size": "size", "duration": "duration", "added": "added_at"}
AGE_DAYS = {"week": 7, "month": 31, "year": 366}          # filtr stáří: videa zveřejněná v posledních N dnech


def published_ts(info: dict | None) -> float | None:
    """Datum zveřejnění z informací yt-dlp (UTC, sekundy): `release_timestamp`, `timestamp`, jinak `release_date` / `upload_date`
    ve tvaru RRRRMMDD. Nesmyslné hodnoty (před rokem 1990 nebo víc než den v budoucnu) se ignorují."""
    if not isinstance(info, dict):
        return None
    cands: list[float] = []
    for k in ("release_timestamp", "timestamp"):
        v = info.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cands.append(float(v))
    for k in ("release_date", "upload_date"):
        v = info.get(k)
        if isinstance(v, str) and re.fullmatch(r"\d{8}", v):
            try:
                cands.append(datetime.datetime(int(v[:4]), int(v[4:6]), int(v[6:]), tzinfo=datetime.timezone.utc).timestamp())
            except ValueError:
                pass
    for ts in cands:
        if 631152000 <= ts <= time.time() + 86400:
            return ts
    return None
THUMB_NAME = re.compile(r"^\d+\.(jpg|jpeg|png|webp|gif)$")
ANIM_NAME = re.compile(r"^\d+\.anim\.(mp4|webm|gif|webp)$")
ANIM_RANK = {".mp4": 0, ".webm": 0, ".m4v": 0, ".webp": 1, ".gif": 2}      # nejdřív nejmenší: video, pak WebP, pak GIF


def norm(text: str | None) -> str:
    """Text pro hledání: malá písmena bez diakritiky a s jednoduchými mezerami."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.lower()).strip()


# --- přidání zdrojů -------------------------------------------------------------------------------
def normalize_url(tok: str) -> str | None:
    """Sjednocená adresa zdroje (schéma a hostitel malými písmeny, bez koncového lomítka), nebo None."""
    try:
        p = urlsplit(tok)
        host = p.hostname
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not host:
        return None
    user, at, hostport = p.netloc.rpartition("@")
    netloc = user + at + hostport.lower()
    path = p.path.rstrip("/") if len(p.path) > 1 else p.path
    return urlunsplit((p.scheme.lower(), netloc, path, p.query, p.fragment))


def parse_urls(text: str) -> tuple[list[str], list[str]]:
    """Adresy z textu (jedna na řádek; prázdné řádky a řádky začínající # se přeskočí). Vrací (adresy, neplatné řádky)."""
    urls, invalid, seen = [], [], set()
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        u = normalize_url(s.split()[0])
        if u is None:
            invalid.append(s[:200])
        elif u not in seen:
            seen.add(u)
            urls.append(u)
    return urls, invalid


def add_sources(db, urls: list[str]) -> dict:
    """Zařadí zdroje do fronty zjišťování. Adresa, která už v katalogu je, se zařadí znovu a nabídne se vše znovu
    (jako „načíst znovu vše“); pokud se právě zjišťuje, přeskočí se."""
    over = urls[MAX_URLS:]
    urls = urls[:MAX_URLS]
    now = time.time()
    added, reloaded, skipped = [], [], []
    with db.conn() as c:
        c.execute("begin immediate")
        have = {r["url"]: r for r in c.execute("select id, url, status from catalog_sources")}
        for u in urls:
            row = have.get(u)
            if row is None:
                cur = c.execute("insert into catalog_sources(url, status, scan_mode, manual, added_at) values(?, 'queued', 'new', 1, ?)", (u, now))
                have[u] = {"id": cur.lastrowid, "url": u, "status": "queued"}
                added.append(cur.lastrowid)
            elif row["status"] == "scanning":
                skipped.append({"url": u, "reason": "právě se zjišťuje"})
            else:
                c.execute("update catalog_sources set status='queued', scan_mode='all', manual=1, error=null where id=?", (row["id"],))
                reloaded.append(row["id"])
        c.execute("commit")
    skipped += [{"url": u, "reason": f"překročen limit {MAX_URLS} adres najednou"} for u in over]
    return {"added": added, "reloaded": reloaded, "skipped": skipped}


def thumbs_dir(data, settings) -> Path:
    """Složka miniatur katalogu (nastavení, jinak <data>/catalog/thumbs)."""
    d = str(settings.get("catalog_thumbs_dir") or "").strip()
    return Path(d).expanduser() if d else Path(data) / "catalog" / "thumbs"


def remove_thumb(folder: Path | None, name: str | None) -> None:
    if folder and name and THUMB_NAME.match(name):
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError:
            pass


def remove_anim(folder: Path | None, name: str | None) -> None:
    if folder and name and ANIM_NAME.match(name):
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError as e:
            log.warning("animace %s se nepodařilo smazat: %s", name, e)


def disk_usage(folder: Path) -> dict:
    """Místo, které zabírají miniatury a animace katalogu: {thumbs: {count, bytes}, anims: {count, bytes}}."""
    out = {"thumbs": {"count": 0, "bytes": 0}, "anims": {"count": 0, "bytes": 0}}
    try:
        with os.scandir(folder) as it:
            for e in it:
                kind = "anims" if ANIM_NAME.match(e.name) else "thumbs" if THUMB_NAME.match(e.name) else None
                if kind and e.is_file(follow_symlinks=False):
                    out[kind]["count"] += 1
                    out[kind]["bytes"] += e.stat(follow_symlinks=False).st_size
    except OSError:
        pass
    return out


def delete_anims(db, folder: Path) -> dict:
    """Smaže všechny soubory animací (i osiřelé) a položkám vrátí „animace čeká“ (adresa zůstane, takže se při zapnutém stahování
    animací stáhnou znovu). Vrací {files, bytes, items}."""
    files = size = 0
    try:
        with os.scandir(folder) as it:
            for e in list(it):
                if ANIM_NAME.match(e.name) and e.is_file(follow_symlinks=False):
                    n = e.stat(follow_symlinks=False).st_size
                    try:
                        Path(e.path).unlink()
                        files += 1
                        size += n
                    except OSError as ex:
                        log.warning("animaci %s se nepodařilo smazat: %s", e.name, ex)
    except OSError:
        pass
    with db.conn() as c:
        items = c.execute("update catalog_items set anim_file=null, updated_at=? where anim_file is not null", (time.time(),)).rowcount
    return {"files": files, "bytes": size, "items": items}


def delete_source(db, sid: int, folder: Path | None = None, keep_items: bool = False) -> bool:
    """Odebere zdroj. Výchozí: smaže zdroj, jeho položky (a paměť o nich) i miniatury a animace. `keep_items`: zdroj se jen „odpojí“
    (stav `detached`): zmizí ze seznamu zdrojů a už se nezjišťuje ani neobnovuje, ale jeho videa zůstanou v katalogu (složka
    stahování zůstává, ve filtru je jako „odebraný zdroj“); znovupřidání stejné adresy zdroj připojí zpět. Fronta stahování a
    už stažená videa se tím nemění ani v jednom případě."""
    if keep_items:
        with db.conn() as c:
            return c.execute("update catalog_sources set status='detached', manual=0 where id=? and status != 'detached'", (sid,)).rowcount > 0
    with db.conn() as c:
        c.execute("begin immediate")
        names = [r["thumb_file"] for r in c.execute("select thumb_file from catalog_items where source_id=? and thumb_file != ''", (sid,))]
        anims = [r["anim_file"] for r in c.execute("select anim_file from catalog_items where source_id=? and anim_file != ''", (sid,))]
        c.execute("delete from catalog_items where source_id=?", (sid,))
        n = c.execute("delete from catalog_sources where id=?", (sid,)).rowcount
        c.execute("commit")
    for name in names:
        remove_thumb(folder, name)
    for name in anims:
        remove_anim(folder, name)
    return bool(n)


def rescan_source(db, sid: int, mode: str) -> bool | None:
    """Zařadí zdroj znovu do fronty zjišťování. None = zdroj není; False = právě se zjišťuje."""
    if mode not in ("new", "all"):
        raise ValueError(mode)
    with db.conn() as c:
        c.execute("begin immediate")
        r = c.execute("select status from catalog_sources where id=?", (sid,)).fetchone()
        if r is None:
            c.execute("rollback")
            return None
        if r["status"] == "detached":                                   # odebraný zdroj se neobnovuje (vrátí ho jen znovupřidání adresy)
            c.execute("rollback")
            return None
        if r["status"] == "scanning":
            c.execute("rollback")
            return False
        c.execute("update catalog_sources set status='queued', scan_mode=?, manual=1, error=null where id=?", (mode, sid))
        c.execute("commit")
    return True


def rescan_all(db) -> int:
    """Obnovení všech zdrojů najednou (jen nová videa); zdroj, který se právě zjišťuje, a odebrané zdroje se přeskočí."""
    with db.conn() as c:
        return c.execute("update catalog_sources set status='queued', scan_mode='new', manual=1, error=null where status in ('done','error','queued')").rowcount


# --- čtení seznamu zdroje -------------------------------------------------------------------------
def thumb_candidates(info: dict) -> list[str]:
    """Adresy miniatur od nejlepší: seznam od konce (yt-dlp ho řadí vzestupně podle kvality, poslední je největší; rozměry
    u největších často neuvádí), nakonec `thumbnail` jako jistota. Největší varianty starším videím chybějí (404), proto
    se zkouší postupně shora dolů."""
    urls: list[str] = []
    for u in [*reversed([t.get("url") for t in (info.get("thumbnails") or [])]), info.get("thumbnail")]:
        if u and u not in urls:
            urls.append(u)
    return urls


def anim_candidate(info: dict) -> str | None:
    """Adresa animovaného náhledu, kterou yt-dlp vrací mezi miniaturami: GIF, MP4/WebM nebo WebP s „anim“ v adrese či id
    (běžné statické WebP miniatury se nepočítají). Z více adres se bere nejmenší formát (video před WebP před GIF)."""
    best: tuple[int, str] | None = None
    for t in [*(info.get("thumbnails") or []), {"url": info.get("thumbnail")}]:
        u = t.get("url") if isinstance(t, dict) else None
        if not u or not isinstance(u, str) or not u.startswith("http"):
            continue
        ext = Path(urlsplit(u).path).suffix.lower()
        if ext not in ANIM_RANK:
            continue
        if ext == ".webp" and "anim" not in (u + str(t.get("id") or "")).lower():
            continue
        if best is None or ANIM_RANK[ext] < best[0]:
            best = (ANIM_RANK[ext], u)
    return best[1] if best else None


def anim_source(info: dict) -> str | None:
    """Animace pro položku: nejdřív hotová animace mezi miniaturami, jinak storyboard (`sb:<JSON>`, složí se ffmpegem)."""
    return anim_candidate(info) or storyboard.candidate(info)


def _thumb(e: dict) -> str | None:
    c = thumb_candidates(e)
    return c[0] if c else None


def _entry_url(e: dict) -> str | None:
    u = e.get("url") or e.get("webpage_url")
    if u and u.startswith("http"):
        return u
    if (e.get("ie_key") or e.get("extractor_key")) == "Youtube" and e.get("id"):
        return f"https://www.youtube.com/watch?v={e['id']}"
    return u


def _flatten(entries) -> list[dict]:
    """Ploché položky seznamu. Klíč je „extraktor id“ (stejný tvar jako v archivu yt-dlp); extraktor se bere jen z položky
    samotné, nikdy z playlistu (jiný extraktor by klíč zkreslil). Bez něj je klíčem adresa."""
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
        if not u or not u.startswith("http"):
            continue
        ie = (e.get("ie_key") or e.get("extractor_key") or "").lower()
        key = f"{ie} {e['id']}" if ie and e.get("id") else u
        cands = thumb_candidates(e)
        out.append({"key": key, "id": e.get("id") if not ie else None, "url": u, "title": e.get("title"),
                    "channel": e.get("channel") or e.get("uploader"), "duration": e.get("duration"), "published_at": published_ts(e),
                    "thumb_url": cands[0] if cands else None, "thumb_alts": cands[1:1 + THUMB_ALTS_MAX], "anim_url": anim_candidate(e)})
    return out


def _dedupe(entries: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in entries:
        if e["key"] not in seen:
            seen.add(e["key"])
            out.append(e)
    return out


PAGE_MAX_PAGES = 200
PAGE_TIMEOUT = 1800           # celé zjištění zdroje typu „stránka“ (s)


async def list_page(url: str, ctx, cause: Exception | None = None) -> dict:
    """Zdroj typu „stránka“ (web, který yt-dlp nezná): díly se najdou jako opakující se odkazy a další stránky seznamu podle
    parametru stránkování. Nejdřív rychle z běžného HTML; když se tak seznam nenajde a je zapnutý prohlížeč
    (`catalog_slow_browser`), stránky se vykreslí v Chromiu (pomalá vrstva, jeden prohlížeč pro všechny stránky).
    Vyhodí ResolveError."""
    slow = bool(ctx.settings.get("catalog_slow_browser"))
    try:
        final, cfg, renderer = url, None, None
        try:
            text, final = await pagelist.fetch(url, ctx.settings)
        except pagelist.PageError as e:                                 # výpadek, 403, 5xx: není to „nepodporovaný web“
            if slow and BLOCKED_RE.search(str(e)):                      # web odmítá prostý dotaz (otisk spojení), prohlížeč ho nejspíš pustí
                renderer = sniffer.Renderer(ctx)
            else:
                raise ResolveError(str(e), "network") from e
        if renderer is None:
            try:
                cfg = pagelist.detect(text, final)
            except pagelist.PageError:
                if not slow:
                    raise
                renderer = sniffer.Renderer(ctx)
    except pagelist.PageError as e:
        why = f"web není podporovaný a seznam videí se na stránce nenašel ({e})"
        raise ResolveError(why + ("" if slow else "; zapněte v Nastavení › Katalog prohlížeč pro pomalé weby"), "unsupported") from cause or e
    if renderer is None:
        return await _page_entries(url, ctx, cfg, None)
    async with renderer as rd:
        try:
            text, final = await rd.render(final)
            cfg = pagelist.detect(text, final)
        except pagelist.PageError as e:
            raise ResolveError(f"web není podporovaný a seznam videí se na stránce nenašel ({e})", "unsupported") from cause or e
        return await _page_entries(url, ctx, cfg, rd)


async def _page_entries(url: str, ctx, cfg: dict, rd) -> dict:
    """Projde stránky seznamu podle zjištěné konfigurace; `rd` je prohlížeč (vykreslené stránky) nebo None (běžné HTML)."""
    items = [dict(i) for i in cfg["items"]]
    seen = {i["url"] for i in items}
    complete = True
    if cfg.get("page_param") or cfg.get("page_template"):
        for k in range(1, PAGE_MAX_PAGES):
            try:
                await asyncio.sleep(1.0)                                   # šetrně k webu
                nxt = pagelist.page_url(url, cfg, k)
                text, final = await (rd.render(nxt) if rd else pagelist.fetch(nxt, ctx.settings))
            except (pagelist.PageError, ResolveError) as e:
                complete = complete and any(f"HTTP {c}" in str(e) for c in (404, 410))     # za poslední stránkou vrací mnoho webů 404
                break
            got = pagelist.items_from(text, final, cfg["item_regex"])
            fresh = [i for i in got if i["url"] not in seen]
            if not fresh:
                complete = complete and bool(got)                       # stránka bez jediného dílu (captcha, prázdný render) = neúplné
                break
            seen.update(i["url"] for i in fresh)
            items += fresh
        else:
            complete = False
    if not (cfg.get("page_param") or cfg.get("page_template")):
        complete = False                                                # bez stránkování nevíme, zda seznam nekončí „posledními díly“
    entries = [{"key": i["url"], "id": None, "url": i["url"], "title": i.get("title") or None, "channel": None, "duration": None,
                "thumb_url": None, "thumb_alts": []} for i in items]
    return {"kind": "page", "title": cfg.get("title") or domain(url), "thumb_url": None, "entries": entries, "complete": complete}


async def list_source(url: str, ctx) -> dict:
    """Seznam videí zdroje (bez stahování): {kind, title, thumb_url, entries[], complete}. Vyhodí ResolveError.
    `complete` je False, když se u kanálu nepodařilo načíst některou záložku (pak se nepovažuje za úplný seznam)."""
    base = youtube_channel_base(url)
    if base:
        tabs = ctx.settings.get("channel_tabs") or ["videos"]
        entries, title, thumb, err = [], None, None, None
        for tab in tabs:
            try:
                info = await ytdlp.probe(f"{base}/{tab}", ctx, timeout=LIST_TIMEOUT)
            except ResolveError as e:
                err = err or e
                continue
            title = title or info.get("channel") or info.get("uploader") or (info.get("title") or "").split(" - ")[0]
            thumb = thumb or _thumb(info)
            entries += _flatten(info.get("entries"))
        if not entries:
            raise err or ResolveError("kanál je prázdný", "unsupported")
        return {"kind": "channel", "title": title or domain(url), "thumb_url": thumb, "entries": _dedupe(entries), "complete": err is None}

    try:
        info = await ytdlp.probe(url, ctx, timeout=LIST_TIMEOUT)
    except ResolveError as e:
        if e.kind != "unsupported":
            raise
        try:
            return await asyncio.wait_for(list_page(url, ctx, e), PAGE_TIMEOUT)
        except asyncio.TimeoutError:
            raise ResolveError("načtení stránek seznamu trvá příliš dlouho", "network") from None
    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        entries = _dedupe(_flatten(info.get("entries")))
        if not entries:
            lists = nested.list_infos(info.get("entries"))[:nested.MAX_LISTS]
            if lists:                                                 # např. záložka „Playlisty“: zdroj je seznam playlistů k výběru
                return {"kind": "playlists", "title": info.get("title") or info.get("channel") or info.get("uploader") or domain(url),
                        "thumb_url": _thumb(info), "entries": [], "playlists": lists, "complete": True}
            raise ResolveError("zdroj je prázdný", "unsupported")
        slug, slug_channel = url_list_name(url)
        is_channel = bool(info.get("channel_id") and info.get("id") == info.get("channel_id")) or slug_channel
        authors = {e["channel"] for e in entries if e.get("channel")}
        title = (info.get("title") or info.get("channel") or info.get("uploader")
                 or (authors.pop() if len(authors) == 1 else None) or slug or domain(url))
        return {"kind": "channel" if is_channel else "playlist", "title": title, "thumb_url": _thumb(info), "entries": entries,
                "complete": True}

    ie = (info.get("extractor_key") or "").lower()
    key = f"{ie} {info['id']}" if ie and info.get("id") else (info.get("webpage_url") or url)
    return {"kind": "video", "title": info.get("title") or domain(url), "thumb_url": _thumb(info), "complete": True,
            "entries": [{"key": key, "id": None, "url": info.get("webpage_url") or url, "title": info.get("title"),
                         "channel": info.get("channel") or info.get("uploader"), "duration": info.get("duration"),
                         "thumb_url": _thumb(info), "thumb_alts": thumb_candidates(info)[1:1 + THUMB_ALTS_MAX],
                         "height": ytdlp.best_height(info), "size": ytdlp.size_estimate(info), "detail_state": "done",
                         "anim_url": anim_source(info)}]}


# --- uložení seznamu ------------------------------------------------------------------------------
def downloaded_sets(db, data) -> tuple[set[str], set[str], set[str]]:
    """Co už bylo staženo: řádky archivu yt-dlp („extraktor id“), samotná id z archivu a adresy z historie."""
    keys: set[str] = set()
    try:
        for line in (data / "archive.txt").read_text("utf-8", errors="replace").splitlines():
            if line.strip():
                keys.add(line.strip())
    except OSError:
        pass
    ids = {k.split(" ", 1)[-1] for k in keys}
    urls = {r["url"] for r in db.query("select url from jobs where status='done'")}
    return keys, ids, urls


def _unavailable(e: dict) -> bool:
    return (e.get("title") or "").strip().lower() in UNAVAILABLE_TITLES


def apply_listing(db, sid: int, listing: dict, mode: str, dl_keys: set[str], dl_ids: set[str], dl_urls: set[str]) -> dict | None:
    """Uloží zjištěný seznam. Vrací počty, nebo None, když zdroj mezitím zmizel."""
    now = time.time()
    entries = listing["entries"]
    kind, title = listing["kind"], listing.get("title")
    added = reoffered = restored = missing = 0
    seen: set[str] = set()
    with db.conn() as c:
        c.execute("begin immediate")
        if c.execute("select 1 from catalog_sources where id=?", (sid,)).fetchone() is None:
            c.execute("rollback")
            return None
        existing = {r["key"]: dict(r) for r in c.execute("select id, key, state, title, channel from catalog_items where source_id=?", (sid,))}
        for pos, e in enumerate(entries):
            key = e["key"]
            seen.add(key)
            unavailable = _unavailable(e)
            hit = existing.get(key)
            if hit:
                iid, state = hit["id"], hit["state"]
                if unavailable:                                   # soukromé nebo smazané: skrýt (mimo ty, co už se stahují)
                    if state == "new":
                        c.execute("update catalog_items set state='gone', pos=?, updated_at=? where id=?", (pos, now, iid))
                    else:
                        c.execute("update catalog_items set pos=? where id=?", (pos, iid))
                    continue
                new_title = e.get("title") or hit["title"]
                new_channel = e.get("channel") or hit["channel"]
                c.execute("update catalog_items set pos=?, title=?, channel=?, duration=coalesce(?, duration), thumb_url=coalesce(?, thumb_url), "
                          "search=?, updated_at=? where id=?",
                          (pos, new_title, new_channel, e.get("duration"), e.get("thumb_url"), norm(f"{new_title or ''} {new_channel or ''}"), now, iid))
                if state == "gone":                               # zase dostupné
                    c.execute("update catalog_items set state='new' where id=?", (iid,))
                    restored += 1
                elif mode == "all" and state in ("removed", "done"):
                    c.execute("update catalog_items set state='new', job_id=null, "
                              "rejected_before=case when ?='removed' then 1 else rejected_before end, "
                              "downloaded_before=case when ?='done' then 1 else downloaded_before end where id=?", (state, state, iid))
                    reoffered += 1
                continue
            downloaded = key in dl_keys or e["url"] in dl_urls or bool(e.get("id") and e["id"] in dl_ids)
            c.execute("insert into catalog_items(source_id, key, url, host, title, channel, duration, thumb_url, thumb_alts, height, size, search, pos, "
                      "state, downloaded_before, detail_state, added_at, updated_at, anim_url, published_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (sid, key, e["url"], domain(e["url"]), e.get("title"), e.get("channel"), e.get("duration"), e.get("thumb_url"),
                       json.dumps(e["thumb_alts"]) if e.get("thumb_alts") else None, e.get("height"),
                       e.get("size"), norm(f"{e.get('title') or ''} {e.get('channel') or ''}"), pos, "gone" if unavailable else "new",
                       1 if downloaded else 0, "failed" if unavailable else e.get("detail_state", "pending"), now, now, e.get("anim_url"), e.get("published_at")))
            added += 1
        if listing.get("complete", True):                         # videa, která ze zdroje zmizela, se skryjí
            gone = [(now, h["id"]) for k, h in existing.items() if h["state"] == "new" and k not in seen]
            c.executemany("update catalog_items set state='gone', updated_at=? where id=?", gone)
            missing = len(gone)
        folder = sanitize_filename(title or "") if kind in ("channel", "playlist", "page") and title else None
        c.execute("update catalog_sources set kind=?, title=?, title_search=?, thumb_url=?, folder=?, status=case when status='detached' then 'detached' else 'done' end, error=null, "
                  "scan_mode=case when scan_mode=? then 'new' else scan_mode end, last_scan=? where id=?",
                  (kind, title, norm(title), listing.get("thumb_url"), folder or None, mode, now, sid))
        c.execute("commit")
    return {"added": added, "reoffered": reoffered, "restored": restored, "missing": missing, "total": len(entries)}


# --- dotazy ---------------------------------------------------------------------------------------
def _like(tok: str) -> str:
    return "%" + tok.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _where(source: int | None, q: str, res: list[str] | None, state: list[str] | None, anim: list[str] | None = None,
           age: str = "", dur: list[str] | None = None) -> tuple[str, list]:
    """Společná část dotazů (FROM … WHERE …) pro zobrazení i výběr položek. `state` (sjednocení): new, queued, downloaded,
    rejected, gone (výchozí jsou viditelné new a queued)."""
    where, args = [], []
    states = [x for x in (state or []) if x in ("new", "queued", "downloaded", "rejected", "gone")]
    plain = [x for x in states if x in ("new", "queued", "gone")]
    flags = [x for x in states if x in ("downloaded", "rejected")]
    if not states:
        where.append("i.state in ('new','queued')")
    else:
        parts = []
        if plain:
            parts.append("i.state in (%s)" % ",".join("?" * len(plain)))
            args += plain
        if flags:
            fl = " or ".join({"downloaded": "i.downloaded_before=1", "rejected": "i.rejected_before=1"}[f] for f in flags)
            parts.append(f"(i.state in ('new','queued') and ({fl}))")
        where.append("(" + " or ".join(parts) + ")")
    if source:
        where.append("i.source_id=?")
        args.append(int(source))
    for tok in norm((q or "")[:MAX_QUERY_CHARS]).split()[:MAX_QUERY_TOKENS]:
        where.append("(i.search || ' ' || coalesce(s.title_search, '')) like ? escape '\\'")
        args.append(_like(tok))
    want = {x for x in (anim or []) if x in ("yes", "no")}
    if want == {"yes"}:                                                       # s animací / bez animace (obojí = bez filtru)
        where.append("(i.anim_file is not null and i.anim_file != '')")
    elif want == {"no"}:
        where.append("(i.anim_file is null or i.anim_file = '')")
    if age in AGE_DAYS:                                                       # jen videa se známým datem zveřejnění
        where.append("(i.published_at > ?)")
        args.append(time.time() - AGE_DAYS[age] * 86400)
    lengths = [DUR_BUCKETS[d] for d in (dur or []) if d in DUR_BUCKETS]
    if lengths:                                                               # délka: sjednocení vybraných intervalů
        where.append("(" + " or ".join(f"({b})" for b in lengths) + ")")
    buckets = [RES_BUCKETS[r] for r in (res or []) if r in RES_BUCKETS]
    if buckets:
        where.append("(" + " or ".join(f"({b})" for b in buckets) + ")")
    return "from catalog_items i join catalog_sources s on s.id=i.source_id where " + " and ".join(where), args


def query_items(db, source: int | None = None, q: str = "", res: list[str] | None = None, state: list[str] | None = None,
                sort: str = "pos", direction: str = "asc", limit: int = 100, offset: int = 0, anim: list[str] | None = None,
                age: str = "", dur: list[str] | None = None) -> dict:
    """Položky katalogu s filtry, řazením a stránkováním."""
    sql_from, args = _where(source, q, res, state, anim, age, dur)
    d = "desc" if str(direction).lower() == "desc" else "asc"
    col = SORT_COLUMNS.get(sort)
    if sort == "published":      # neznámé datum (null i 0) vždy nakonec
        order = f"(i.published_at is null or i.published_at = 0), i.published_at {d}, s.title_search, i.source_id, i.pos, i.id"
    elif col:       # čísla: neznámé hodnoty vždy nakonec
        order = f"(i.{col} is null), i.{col} {d}, s.title_search, i.source_id, i.pos, i.id"
    elif sort == "source":
        order = f"s.title_search {d}, i.source_id {d}, i.pos, i.id"
    else:
        order = f"s.title_search, i.source_id, i.pos {d}, i.id"
    limit, offset = max(1, min(int(limit), 500)), max(0, min(int(offset), MAX_OFFSET))
    total = db.query(f"select count(*) n {sql_from}", args)[0]["n"]
    rows = db.query(f"select i.*, s.title as source_title, s.folder as source_folder, s.kind as source_kind {sql_from} "
                    f"order by {order} limit ? offset ?", [*args, limit, offset])
    return {"total": total, "items": [item_out(r) for r in rows]}


def _id_list(v, what: str) -> list[int]:
    if not isinstance(v, list) or any(isinstance(i, bool) or not isinstance(i, int) or not 0 < i < 2 ** 62 for i in v):
        raise ValueError(f"{what} must be a list of ids")
    return list(dict.fromkeys(v))


def select_ids(db, spec) -> list[int]:
    """Položky vybrané buď výčtem čísel (`ids`), nebo popisem filtru (`filter`: source, q, res, state, anim) s výjimkami
    (`exclude`). Hromadné akce se tak posílají jako filtr, ne jako tisíce čísel."""
    if not isinstance(spec, dict):
        raise ValueError("selection must be an object")
    if "ids" in spec:
        ids = _id_list(spec["ids"], "ids")
        if len(ids) > MAX_SELECT:
            raise ValueError("too many items")
        return ids
    f = spec.get("filter")
    if not isinstance(f, dict):
        raise ValueError("selection needs ids or filter")
    src, q = f.get("source"), f.get("q", "")
    res, state, anim = f.get("res") or [], f.get("state") or [], f.get("anim") or []
    if (src is not None and (isinstance(src, bool) or not isinstance(src, int))) or not isinstance(q, str) \
            or not isinstance(res, list) or not isinstance(state, list) or not isinstance(anim, list) \
            or not all(isinstance(x, str) for x in res + state + anim):
        raise ValueError("invalid filter")
    dur = f.get("dur") or []
    if not isinstance(dur, list) or not all(isinstance(x, str) for x in dur):
        raise ValueError("invalid filter")
    sql_from, args = _where(src, q, res, state, anim, f.get("age") if isinstance(f.get("age"), str) else "", dur)
    rows = db.query(f"select i.id {sql_from} order by i.id limit ?", [*args, MAX_SELECT + 1])
    if len(rows) > MAX_SELECT:
        raise ValueError("too many items")
    skip = set(_id_list(spec.get("exclude") or [], "exclude"))
    return [r["id"] for r in rows if r["id"] not in skip]


def remove_items(db, ids: list[int], folder: Path | None = None) -> dict:
    """Odstraní položky z katalogu (stav `removed`, zdroj si je pamatuje) a smaže jejich miniatury. Položky ve frontě
    stahování (`queued`) se neodstraňují."""
    removed, names, anims = 0, [], []
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        mark = ",".join("?" * len(chunk))
        with db.conn() as c:
            c.execute("begin immediate")
            rows = c.execute(f"select id, thumb_file, anim_file from catalog_items where id in ({mark}) and state in ('new','gone')", chunk).fetchall()
            got = [r["id"] for r in rows]
            if got:
                c.execute(f"update catalog_items set state='removed', thumb_file=null, anim_file=null, job_id=null, updated_at=? where id in ({','.join('?' * len(got))})",
                          [time.time(), *got])
            c.execute("commit")
        names += [r["thumb_file"] for r in rows if r["thumb_file"]]
        anims += [r["anim_file"] for r in rows if r["anim_file"]]
        removed += len(got)
    for n in names:
        remove_thumb(folder, n)
    for n in anims:
        remove_anim(folder, n)
    return {"removed": removed, "skipped": len(ids) - removed}


def _forget_job(db, r: dict) -> dict | None:
    """Popis videa pro vyřazení z archivu yt-dlp: z klíče položky („extraktor id“); u položek s klíčem-adresou (zdroje „Stránka“)
    z poslední úlohy se stejnou adresou, která video stáhla nebo ho přeskočila."""
    ext, _, vid = (r["key"] or "").partition(" ")
    if vid and not r["key"].startswith("http"):
        return {"url": r["url"], "info": json.dumps({"id": vid, "extractor_key": ext})}
    j = db.query("select url, info from jobs where url=? and status in ('done','skipped') order by id desc limit 1", (r["url"],))
    return {"url": j[0]["url"], "info": j[0]["info"]} if j else {"url": r["url"], "info": None}


_QUEUE_LOCK = threading.Lock()


def queue_items(db, runner, ids: list[int], force: bool = False) -> dict:
    with _QUEUE_LOCK:                                                   # dvojklik / souběžné požadavky nesmí zařadit totéž dvakrát
        return _queue_items(db, runner, ids, force)


def _queue_items(db, runner, ids: list[int], force: bool = False) -> dict:
    """Zařadí vybrané položky (stav `new`) do fronty stahování, do složky s názvem zdroje (kanál nebo playlist; u jednotlivého
    videa bez složky, nezávisle na nastavení „samostatná složka“). Dříve stažené se bez `force` přeskočí; s `force` se
    nejdřív vyřadí z archivu yt-dlp, aby se stáhly znovu. Adresa, která už ve frontě je, se jen propojí s položkou."""
    res = {"queued": 0, "linked": 0, "skipped_downloaded": 0, "skipped_state": 0}
    found: dict[int, dict] = {}
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        for r in db.query(f"select i.*, s.folder as source_folder from catalog_items i join catalog_sources s on s.id=i.source_id "
                          f"where i.id in ({','.join('?' * len(chunk))})", chunk):
            found[r["id"]] = r
    todo = []
    for i in ids:
        r = found.get(i)
        if r is None or r["state"] != "new":
            res["skipped_state"] += 1
        elif r["downloaded_before"] and not force:
            res["skipped_downloaded"] += 1
        else:
            todo.append(r)
    for r in todo:
        if force:                                                       # vynucené stažení: nejdřív z archivu, jinak by ho yt-dlp přeskočil
            fj = _forget_job(db, r)
            if fj:
                runner.archive_forget_many([fj])
        kw = {"subdir": r["source_folder"]} if r["source_folder"] else {}
        jid, new = runner.add(r["url"], source="catalog", auto_confirm=True, catalog_item_id=r["id"], **kw)
        with db.conn() as c:
            c.execute("update catalog_items set state='queued', job_id=?, detail_error=null, updated_at=? where id=? and state='new'",
                      (jid, time.time(), r["id"]))
        res["queued" if new else "linked"] += 1
    return res


def reconcile(db, folder: Path | None = None) -> dict:
    """Srovná položky ve frontě s úlohami: staženo → z katalogu zmizí (zdroj si ji pamatuje, miniatura se smaže);
    selhalo, zrušeno, přeskočeno nebo úloha zmizela → položka se vrátí mezi nová s poznámkou."""
    done = back = 0
    rows = db.query("select i.id, i.job_id, i.thumb_file, i.anim_file, j.status js, j.error je from catalog_items i left join jobs j on j.id=i.job_id where i.state='queued'")
    for r in rows:
        js = r["js"]
        if js == "expanded":                                            # adresa se rozbalila jako playlist: rozhodují potomci
            kids = [k["status"] for k in db.query("select status from jobs where parent_id=?", (r["job_id"],))]
            if not kids or any(k in ACTIVE_JOB for k in kids):
                if kids:
                    continue
                js = "failed"
                r = {**r, "je": "adresa se rozbalila na seznam bez videí"}
            elif "done" in kids:
                js = "done"
            else:
                js = "failed"
                r = {**r, "je": "žádné video ze seznamu se nestáhlo"}
        elif js in ACTIVE_JOB:
            continue
        now = time.time()
        if js == "done":
            with db.conn() as c:
                c.execute("update catalog_items set state='done', thumb_file=null, anim_file=null, detail_error=null, updated_at=? where id=? and state='queued'", (now, r["id"]))
            remove_thumb(folder, r["thumb_file"])
            remove_anim(folder, r["anim_file"])
            done += 1
            continue
        if js == "skipped" and "archiv" in (r["je"] or "").lower():       # stažené jinudy: příště nabídnout „stáhnout znovu“
            with db.conn() as c:
                c.execute("update catalog_items set downloaded_before=1 where id=?", (r["id"],))
        note = {"failed": f"{DL_NOTE} selhalo: {(r['je'] or '').strip()}", "cancelled": f"{DL_NOTE} bylo zrušeno",
                "skipped": f"{DL_NOTE} přeskočeno: {(r['je'] or '').strip()}", None: f"{DL_NOTE}: úloha už není v historii"}.get(js, f"{DL_NOTE}: {js}")
        with db.conn() as c:
            c.execute("update catalog_items set state='new', job_id=null, detail_error=?, updated_at=? where id=? and state='queued'", (note[:300], now, r["id"]))
        back += 1
    return {"done": done, "back": back}


def item_out(r: dict) -> dict:
    return {"id": r["id"], "source_id": r["source_id"], "source_title": r.get("source_title"), "source_folder": r.get("source_folder"),
            "title": r["title"], "channel": r["channel"], "url": r["url"], "duration": r["duration"], "height": r["height"],
            "size": r["size"], "published": r["published_at"] or None, "thumb_url": r["thumb_url"], "has_thumb": bool(r["thumb_file"]),
            "thumb": f"/api/catalog/thumb/{r['id']}?v={int(r['updated_at'] or 0)}" if r["thumb_file"] else None,
            "anim": f"/api/catalog/anim/{r['id']}?v={int(r['updated_at'] or 0)}" if r.get("anim_file") else None,
            "anim_kind": (("video" if r["anim_file"].endswith((".mp4", ".webm")) else "image") if r.get("anim_file") else None), "state": r["state"],
            "downloaded_before": bool(r["downloaded_before"]), "rejected_before": bool(r["rejected_before"]),
            "detail_state": r["detail_state"], "detail_error": r["detail_error"], "job_id": r["job_id"],
            "download_error": r["detail_error"] if (r["detail_error"] or "").startswith(DL_NOTE) else None}


def _children(s: dict) -> list[dict]:
    try:
        return json.loads(s["children"] or "[]")
    except ValueError:
        return []


def sources_out(db) -> dict:
    """Zdroje se stavem zjišťování a počty videí, plus celkové počty."""
    counts = {r["source_id"]: r for r in db.query(
        "select source_id, sum(state in ('new','queued')) items, sum(state='queued') queued, "
        "sum(state in ('new','queued') and detail_state='done') details_done, sum(state='gone') gone, "
        "sum(state in ('new','queued') and downloaded_before=1) downloaded_before, "
        "sum(state in ('new','queued') and rejected_before=1) rejected_before, count(*) total from catalog_items group by source_id")}
    out, detached = [], []
    for s in db.query("select * from catalog_sources order by id"):
        c = counts.get(s["id"]) or {}
        if s["status"] == "detached":                                   # odebraný zdroj: jen kvůli filtru jeho ponechaných videí
            if c.get("items"):
                detached.append({"id": s["id"], "title": s["title"] or s["url"], "items": c["items"]})
            continue
        out.append({"id": s["id"], "url": s["url"], "kind": s["kind"], "title": s["title"], "folder": s["folder"], "status": s["status"],
                    "error": s["error"], "added_at": s["added_at"], "last_scan": s["last_scan"],
                    "items": c.get("items") or 0, "queued": c.get("queued") or 0, "details_done": c.get("details_done") or 0,
                    "gone": c.get("gone") or 0, "downloaded_before": c.get("downloaded_before") or 0,
                    "rejected_before": c.get("rejected_before") or 0,
                    # vyřízený zdroj: sken dokončen, žádné video k vybrání ani ve frontě, ale zdroj nějaká videa měl; po volbě „Ponechat“
                    # se znovu hlásí až když přibudou nová videa (změní se celkový počet)
                    "playlists": _children(s) if s["status"] == "choose" else None,
                    "exhausted": s["status"] == "done" and not c.get("items") and (c.get("total") or 0) > 0 and s["keep_total"] != c.get("total")})
    return {"sources": out, "detached": detached, "items": sum(x["items"] for x in out) + sum(x["items"] for x in detached),
            "scanning": sum(1 for x in out if x["status"] in ("queued", "scanning"))}


def keep_source(db, sid: int) -> bool:
    """Volba „Ponechat“ u vyřízeného zdroje: zdroj se dál zjišťuje a ptát se na něj bude až po příchodu nových videí."""
    with db.conn() as c:
        c.execute("begin immediate")
        if c.execute("select 1 from catalog_sources where id=?", (sid,)).fetchone() is None:
            c.execute("rollback")
            return False
        c.execute("update catalog_sources set keep_total=(select count(*) from catalog_items where source_id=?) where id=?", (sid, sid))
        c.execute("commit")
    return True


# --- zjišťování na pozadí -------------------------------------------------------------------------
def claim_source(db, manual_only: bool = False) -> dict | None:
    """Atomicky převezme nejstarší zdroj čekající ve frontě (stav „zjišťuje se“); režim se přečte až při převzetí.
    `manual_only`: mimo časové okno se zjišťují jen zdroje zařazené ručně."""
    with db.conn() as c:
        c.execute("begin immediate")
        r = c.execute("select * from catalog_sources where status='queued'" + (" and manual=1" if manual_only else "") +
                      " order by id limit 1").fetchone()
        if r is None:
            c.execute("rollback")
            return None
        c.execute("update catalog_sources set status='scanning', error=null where id=?", (r["id"],))
        c.execute("commit")
        return {**dict(r), "status": "scanning"}


def auto_refresh(db, hours: float, now: float | None = None) -> int:
    """Automatické hledání nových videí: zdroje, které se naposledy zjišťovaly před víc než `hours` hodinami (a právě se
    nezjišťují), se zařadí do fronty v režimu „jen nová“ jako automatické (`manual=0`, řídí je časový rozvrh).
    Zdroj s chybou se zkusí znovu po stejném intervalu. Vrací počet zařazených zdrojů."""
    now = time.time() if now is None else now
    with db.conn() as c:
        return c.execute("update catalog_sources set status='queued', manual=0 where status in ('done','error') "
                         "and coalesce(last_scan, 0) < ? and not (status='error' and coalesce(error,'') like 'web není podporovaný%')",
                         (now - hours * 3600,)).rowcount


def _fail(db, sid: int, msg: str) -> None:
    with db.conn() as c:
        c.execute("update catalog_sources set status='error', error=?, last_scan=? where id=?", (msg, time.time(), sid))


def store_choose(db, sid: int, listing: dict) -> None:
    """Zdroj je seznam playlistů: uloží je k výběru (stav `choose`); videa se do katalogu přidají až z playlistů jako samostatných zdrojů."""
    title = listing.get("title")
    with db.conn() as c:
        c.execute("update catalog_sources set kind='playlists', title=?, title_search=?, status='choose', error=null, children=?, last_scan=? "
                  "where id=? and status='scanning'", (title, norm(title or ""), json.dumps(listing["playlists"], ensure_ascii=False), time.time(), sid))


def expand_source(db, sid: int, urls: list[str], folder: Path | None = None) -> dict | None:
    """Zdroj se seznamem playlistů (`choose`): vybrané playlisty přidá jako samostatné zdroje a původní zdroj odebere.
    Vrací {"added", "reloaded", "skipped"} z `add_sources`, nebo None, když zdroj není ve stavu výběru."""
    r = db.query("select status, children from catalog_sources where id=?", (sid,))
    if not r or r[0]["status"] != "choose":
        return None
    try:
        known = [x["url"] for x in json.loads(r[0]["children"] or "[]")]
    except ValueError:
        known = []
    want = [u for u in dict.fromkeys(urls) if u in set(known)][:nested.MAX_LISTS]
    if not want:                                                  # nic platného nevybráno: seznam zůstane, ať o něj uživatel nepřijde
        return {"added": [], "reloaded": [], "skipped": [{"url": u, "reason": "není v seznamu playlistů zdroje"} for u in urls[:20]]}
    res = add_sources(db, want)
    delete_source(db, sid, folder)                                # složka kvůli miniaturám a animacím, které zdroj dřív mohl mít
    return res


async def scan_one(st, src: dict) -> dict:
    """Zjistí seznam jednoho zdroje a uloží ho. Chyba se zapíše ke zdroji (a zdroj zůstane k ručnímu opakování)."""
    db, sid = st.db, src["id"]
    with db.conn() as c:
        n = c.execute("update catalog_sources set status='scanning', error=null where id=? and status != 'detached'", (sid,)).rowcount
    if not n:                                                           # mezitím odebraný (odpojený) nebo smazaný zdroj se nezjišťuje
        return {}
    try:
        listing = await list_source(src["url"], st.runner.ctx())
        if listing.get("kind") == "playlists":
            await asyncio.to_thread(store_choose, db, sid, listing)
            log.info("katalog: %s – seznam %d playlistů k výběru", listing.get("title"), len(listing["playlists"]))
            return {}
        keys, ids, urls = await asyncio.to_thread(downloaded_sets, db, st.data)
        res = await asyncio.to_thread(apply_listing, db, sid, listing, src["scan_mode"], keys, ids, urls)
        if res is not None:
            log.info("katalog: %s – %d videí (+%d, znovu nabídnuto %d, zmizelo %d)", listing.get("title"), res["total"], res["added"],
                     res["reoffered"], res["missing"])
        return res or {}
    except asyncio.CancelledError:
        with db.conn() as c:
            c.execute("update catalog_sources set status='queued' where id=? and status='scanning'", (sid,))
        raise
    except ResolveError as e:
        _fail(db, sid, str(e)[:500])
    except Exception as e:  # noqa: BLE001
        log.exception("katalog: zdroj %s", sid)
        _fail(db, sid, f"{type(e).__name__}: {e}"[:500])
    return {}


async def _sleep(stop: asyncio.Event, sec: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), sec)
    except asyncio.TimeoutError:
        pass


async def task(st, stop: asyncio.Event) -> None:
    """Fronta zjišťování: zdroje se zpracují postupně, nezabírají stahovací sloty. Reaguje na vypnutí aplikace
    (rozpracované zjišťování se zruší a zdroj se vrátí do fronty) a přežije chybu databáze."""
    try:
        with st.db.conn() as c:
            c.execute("update catalog_sources set status='queued' where status='scanning'")    # po restartu pokračovat
    except Exception:  # noqa: BLE001
        log.exception("katalog: obnovení fronty")
    rec = asyncio.create_task(_reconcile_loop(st, stop))      # stav položek se srovnává i během dlouhého zjišťování zdroje
    try:
        await _task_loop(st, stop)
    finally:
        rec.cancel()
        await asyncio.gather(rec, return_exceptions=True)


async def _reconcile_loop(st, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(reconcile, st.db, thumbs_dir(st.data, st.settings))   # staženo / selhalo → stav položek v katalogu
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("katalog: srovnání stavu položek")
        await _sleep(stop, 3)


async def _task_loop(st, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            open_now = schedule.allowed(st.settings.all(), "catalog", db=st.db)           # mimo okno jen ručně zařazené zdroje
            if open_now and st.settings.get("catalog_auto"):
                await asyncio.to_thread(auto_refresh, st.db, float(st.settings.get("catalog_auto_hours") or 24))
            src = await asyncio.to_thread(claim_source, st.db, not open_now)
            if src is None:
                await _sleep(stop, 3)
                continue
            scan = asyncio.create_task(scan_one(st, src))
            waiter = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait({scan, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if scan not in done:
                scan.cancel()
            waiter.cancel()
            await asyncio.gather(scan, waiter, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("katalog: neočekávaná chyba, zkusím znovu za chvíli")
            await _sleep(stop, 5)
            continue
        await _sleep(stop, 1)
