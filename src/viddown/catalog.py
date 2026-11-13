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
import logging
import re
import time
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from .resolvers import ResolveError, ytdlp
from .util import domain, sanitize_filename, url_list_name, youtube_channel_base

log = logging.getLogger("viddown.catalog")

LIST_TIMEOUT = 3600           # načtení seznamu velkého kanálu může trvat dlouho
MAX_URLS = 2000
MAX_QUERY_TOKENS = 10
MAX_QUERY_CHARS = 200
MAX_OFFSET = 10_000_000
UNAVAILABLE_TITLES = ("[private video]", "[deleted video]")

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
                cur = c.execute("insert into catalog_sources(url, status, scan_mode, added_at) values(?, 'queued', 'new', ?)", (u, now))
                have[u] = {"id": cur.lastrowid, "url": u, "status": "queued"}
                added.append(cur.lastrowid)
            elif row["status"] == "scanning":
                skipped.append({"url": u, "reason": "právě se zjišťuje"})
            else:
                c.execute("update catalog_sources set status='queued', scan_mode='all', error=null where id=?", (row["id"],))
                reloaded.append(row["id"])
        c.execute("commit")
    skipped += [{"url": u, "reason": f"překročen limit {MAX_URLS} adres najednou"} for u in over]
    return {"added": added, "reloaded": reloaded, "skipped": skipped}


def delete_source(db, sid: int) -> bool:
    with db.conn() as c:
        c.execute("begin immediate")
        c.execute("delete from catalog_items where source_id=?", (sid,))
        n = c.execute("delete from catalog_sources where id=?", (sid,)).rowcount
        c.execute("commit")
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
        if r["status"] == "scanning":
            c.execute("rollback")
            return False
        c.execute("update catalog_sources set status='queued', scan_mode=?, error=null where id=?", (mode, sid))
        c.execute("commit")
    return True


# --- čtení seznamu zdroje -------------------------------------------------------------------------
def _thumb(e: dict) -> str | None:
    th = [t for t in (e.get("thumbnails") or []) if t.get("url")]
    return th[-1]["url"] if th else e.get("thumbnail")


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
        u = _entry_url(e)
        if not u or not u.startswith("http"):
            continue
        ie = (e.get("ie_key") or e.get("extractor_key") or "").lower()
        key = f"{ie} {e['id']}" if ie and e.get("id") else u
        out.append({"key": key, "id": e.get("id") if not ie else None, "url": u, "title": e.get("title"),
                    "channel": e.get("channel") or e.get("uploader"), "duration": e.get("duration"), "thumb_url": _thumb(e)})
    return out


def _dedupe(entries: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in entries:
        if e["key"] not in seen:
            seen.add(e["key"])
            out.append(e)
    return out


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

    info = await ytdlp.probe(url, ctx, timeout=LIST_TIMEOUT)
    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        entries = _dedupe(_flatten(info.get("entries")))
        if not entries:
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
                         "thumb_url": _thumb(info), "height": ytdlp.best_height(info), "size": ytdlp.size_estimate(info),
                         "detail_state": "done"}]}


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
            c.execute("insert into catalog_items(source_id, key, url, title, channel, duration, thumb_url, height, size, search, pos, state, "
                      "downloaded_before, detail_state, added_at, updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (sid, key, e["url"], e.get("title"), e.get("channel"), e.get("duration"), e.get("thumb_url"), e.get("height"),
                       e.get("size"), norm(f"{e.get('title') or ''} {e.get('channel') or ''}"), pos, "gone" if unavailable else "new",
                       1 if downloaded else 0, "failed" if unavailable else e.get("detail_state", "pending"), now, now))
            added += 1
        if listing.get("complete", True):                         # videa, která ze zdroje zmizela, se skryjí
            gone = [(now, h["id"]) for k, h in existing.items() if h["state"] == "new" and k not in seen]
            c.executemany("update catalog_items set state='gone', updated_at=? where id=?", gone)
            missing = len(gone)
        folder = sanitize_filename(title or "") if kind in ("channel", "playlist") and title else None
        c.execute("update catalog_sources set kind=?, title=?, title_search=?, thumb_url=?, folder=?, status='done', error=null, "
                  "scan_mode=case when scan_mode=? then 'new' else scan_mode end, last_scan=? where id=?",
                  (kind, title, norm(title), listing.get("thumb_url"), folder or None, mode, now, sid))
        c.execute("commit")
    return {"added": added, "reoffered": reoffered, "restored": restored, "missing": missing, "total": len(entries)}


# --- dotazy ---------------------------------------------------------------------------------------
def _like(tok: str) -> str:
    return "%" + tok.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def query_items(db, source: int | None = None, q: str = "", res: list[str] | None = None, state: list[str] | None = None,
                sort: str = "pos", direction: str = "asc", limit: int = 100, offset: int = 0) -> dict:
    """Položky katalogu s filtry, řazením a stránkováním. `state` (sjednocení): new, queued, downloaded, rejected, gone
    (výchozí jsou viditelné new a queued)."""
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
    buckets = [RES_BUCKETS[r] for r in (res or []) if r in RES_BUCKETS]
    if buckets:
        where.append("(" + " or ".join(f"({b})" for b in buckets) + ")")
    d = "desc" if str(direction).lower() == "desc" else "asc"
    col = SORT_COLUMNS.get(sort)
    if col:       # čísla: neznámé hodnoty vždy nakonec
        order = f"(i.{col} is null), i.{col} {d}, s.title_search, i.source_id, i.pos, i.id"
    elif sort == "source":
        order = f"s.title_search {d}, i.source_id {d}, i.pos, i.id"
    else:
        order = f"s.title_search, i.source_id, i.pos {d}, i.id"
    sql_from = "from catalog_items i join catalog_sources s on s.id=i.source_id where " + " and ".join(where)
    limit, offset = max(1, min(int(limit), 500)), max(0, min(int(offset), MAX_OFFSET))
    total = db.query(f"select count(*) n {sql_from}", args)[0]["n"]
    rows = db.query(f"select i.*, s.title as source_title, s.folder as source_folder, s.kind as source_kind {sql_from} "
                    f"order by {order} limit ? offset ?", [*args, limit, offset])
    return {"total": total, "items": [item_out(r) for r in rows]}


def item_out(r: dict) -> dict:
    return {"id": r["id"], "source_id": r["source_id"], "source_title": r.get("source_title"), "source_folder": r.get("source_folder"),
            "title": r["title"], "channel": r["channel"], "url": r["url"], "duration": r["duration"], "height": r["height"],
            "size": r["size"], "thumb_url": r["thumb_url"], "has_thumb": bool(r["thumb_file"]), "state": r["state"],
            "downloaded_before": bool(r["downloaded_before"]), "rejected_before": bool(r["rejected_before"]),
            "detail_state": r["detail_state"], "detail_error": r["detail_error"], "job_id": r["job_id"]}


def sources_out(db) -> dict:
    """Zdroje se stavem zjišťování a počty videí, plus celkové počty."""
    counts = {r["source_id"]: r for r in db.query(
        "select source_id, sum(state in ('new','queued')) items, sum(state='queued') queued, "
        "sum(state in ('new','queued') and detail_state='done') details_done, sum(state='gone') gone, "
        "sum(state in ('new','queued') and downloaded_before=1) downloaded_before, "
        "sum(state in ('new','queued') and rejected_before=1) rejected_before from catalog_items group by source_id")}
    out = []
    for s in db.query("select * from catalog_sources order by id"):
        c = counts.get(s["id"]) or {}
        out.append({"id": s["id"], "url": s["url"], "kind": s["kind"], "title": s["title"], "folder": s["folder"], "status": s["status"],
                    "error": s["error"], "added_at": s["added_at"], "last_scan": s["last_scan"],
                    "items": c.get("items") or 0, "queued": c.get("queued") or 0, "details_done": c.get("details_done") or 0,
                    "gone": c.get("gone") or 0, "downloaded_before": c.get("downloaded_before") or 0,
                    "rejected_before": c.get("rejected_before") or 0})
    return {"sources": out, "items": sum(x["items"] for x in out), "scanning": sum(1 for x in out if x["status"] in ("queued", "scanning"))}


# --- zjišťování na pozadí -------------------------------------------------------------------------
def claim_source(db) -> dict | None:
    """Atomicky převezme nejstarší zdroj čekající ve frontě (stav „zjišťuje se“); režim se přečte až při převzetí."""
    with db.conn() as c:
        c.execute("begin immediate")
        r = c.execute("select * from catalog_sources where status='queued' order by id limit 1").fetchone()
        if r is None:
            c.execute("rollback")
            return None
        c.execute("update catalog_sources set status='scanning', error=null where id=?", (r["id"],))
        c.execute("commit")
        return {**dict(r), "status": "scanning"}


def _fail(db, sid: int, msg: str) -> None:
    with db.conn() as c:
        c.execute("update catalog_sources set status='error', error=?, last_scan=? where id=?", (msg, time.time(), sid))


async def scan_one(st, src: dict) -> dict:
    """Zjistí seznam jednoho zdroje a uloží ho. Chyba se zapíše ke zdroji (a zdroj zůstane k ručnímu opakování)."""
    db, sid = st.db, src["id"]
    with db.conn() as c:
        c.execute("update catalog_sources set status='scanning', error=null where id=?", (sid,))
    try:
        listing = await list_source(src["url"], st.runner.ctx())
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
        msg = "web není podporovaný (další weby přibudou v další etapě katalogu)" if e.kind == "unsupported" and "Unsupported URL" in str(e) else str(e)
        _fail(db, sid, msg[:500])
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
    while not stop.is_set():
        try:
            src = await asyncio.to_thread(claim_source, st.db)
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
