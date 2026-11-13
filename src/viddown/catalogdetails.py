"""Katalog, etapa 2: podrobnosti videí (rozlišení, velikost, délka, nejlepší miniatura) a stahování miniatur.

Pořadí práce: nejdřív se dokončí seznamy všech zdrojů (`catalog.task`), teprve potom se zjišťují podrobnosti. Podrobnosti
se zjišťují po jednom videu s pauzou mezi dotazy na stejný web (`catalog_gap`, režim výkonu ji prodlužuje); různé weby
mohou běžet souběžně (nejvýš `MAX_HOSTS`). Omezení ze strany webu (HTTP 429, ověření „nejsem robot“) web odloží na delší
dobu, která se zdvojnásobuje; smazané nebo soukromé video se označí jen u sebe. Miniatury se stahují zvlášť a rychle.
Pomalá úroveň (prohlížeč u webů bez podpory yt-dlp) přijde s dalšími typy zdrojů.
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import logging
import random
import time
import uuid
from pathlib import Path

import httpx

from . import catalog, schedule, thumbs
from .resolvers import ResolveError, sniffer, ytdlp

log = logging.getLogger("viddown.catalogdetails")

MAX_HOSTS = 3                       # nejvýš tolik webů souběžně
BACKOFF_FIRST = 120.0               # první odložení webu po omezení (s); pak se zdvojnásobuje
BACKOFF_MAX = 7200.0
BACKOFF_LOGIN = 3600.0              # web vyžaduje přihlášení/ověření: zkusit až za hodinu
PERF_MULT = {"full": 1.0, "balanced": 2.0, "eco": 4.0}
THUMB_BATCH = 4
THUMB_CANDIDATES = 10               # kolik kandidátů miniatury se zkusí, než se vzdá (největší varianty starším videím chybějí)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def detail_ctx(st):
    """Kontext pro zjišťování podrobností: vždy video v nejlepší kvalitě, bez ohledu na „jen zvuk“ v nastavení."""
    c = st.runner.ctx()
    settings = {**c.settings, "audio_only": False, "quality": "max"}
    try:
        return dataclasses.replace(c, settings=settings)
    except TypeError:
        c2 = copy.copy(c)
        c2.settings = settings
        return c2


def best_thumbnails(info: dict) -> list[str]:
    return catalog.thumb_candidates(info)


def looks_like_image(path: Path) -> bool:
    try:
        head = path.read_bytes()[:12]
    except OSError:
        return False
    return head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n" or head[:6] in (b"GIF87a", b"GIF89a") or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")


def download_thumb(folder: Path, item_id: int, urls: list[str], referer: str | None = None) -> str | None:
    """Stáhne první použitelnou miniaturu ze seznamu a uloží ji jako `<id>.<přípona>` (starší soubor položky nahradí).
    Vrací název souboru, nebo None."""
    folder.mkdir(parents=True, exist_ok=True)
    for url in urls[:THUMB_CANDIDATES]:
        suffix = Path(url.split("?", 1)[0]).suffix.lower()
        ext = suffix if suffix in IMAGE_EXTS else ".jpg"
        tmp = folder / f"{item_id}{ext}.{uuid.uuid4().hex[:8]}.part"           # vlastní soubor pro každé stažení (souběh s podrobnostmi)
        try:
            if not thumbs.fetch(url, tmp, referer=referer) or not looks_like_image(tmp):
                continue
            final = folder / f"{item_id}{ext}"
            tmp.replace(final)
            for other in IMAGE_EXTS:                          # po změně formátu zůstane jediný soubor
                if other != ext:
                    (folder / f"{item_id}{other}").unlink(missing_ok=True)
            return final.name
        except OSError as e:
            log.debug("miniatura %s: %s", url, e)
        finally:
            tmp.unlink(missing_ok=True)
    return None


def anim_kind(head: bytes) -> str | None:
    """Rozpozná animaci podle obsahu: mp4, webm, gif nebo animovaný webp (VP8X s příznakem animace); jinak None."""
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP" and head[12:16] == b"VP8X" and len(head) > 20 and head[20] & 0x02:
        return "webp"
    return None


def download_anim(folder: Path, item_id: int, url: str, max_bytes: int, referer: str | None = None) -> str | None:
    """Stáhne animovaný náhled do složky miniatur jako `<id>.anim.<přípona>`. Soubor větší než `max_bytes` nebo s jiným
    obsahem (statický obrázek, HTML) se zahodí. Vrací název souboru, nebo None."""
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{item_id}.anim.{uuid.uuid4().hex[:8]}.part"
    try:
        headers = {"User-Agent": thumbs.BROWSER_UA, "Referer": referer} if referer else {"User-Agent": thumbs.UA}
        with httpx.Client(follow_redirects=True, timeout=30, headers=headers) as c:
            with c.stream("GET", url) as r:
                if r.status_code != 200:
                    return None
                if int(r.headers.get("content-length") or 0) > max_bytes:
                    return None
                size = 0
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:                               # velikost se hlídá i bez hlavičky Content-Length
                            return None
                        f.write(chunk)
        with tmp.open("rb") as f:
            kind = anim_kind(f.read(64)) if size else None
        if not kind:
            return None
        final = folder / f"{item_id}.anim.{kind}"
        tmp.replace(final)
        for other in ("mp4", "webm", "gif", "webp"):                       # jediný soubor na položku
            if other != kind:
                (folder / f"{item_id}.anim.{other}").unlink(missing_ok=True)
        return final.name
    except (OSError, ValueError, httpx.HTTPError) as e:
        log.debug("animace %s: %s", url, e)
        return None
    finally:
        tmp.unlink(missing_ok=True)


class DetailWorker:
    def __init__(self, st):
        self.st = st
        self.next_at: dict[str, float] = {}          # web -> čas (monotonic), kdy smí další dotaz
        self.backoff: dict[str, dict] = {}           # web -> {until, delay, reason}
        self.active: dict[str, asyncio.Task] = {}
        self.slow_task: asyncio.Task | None = None   # pomalá vrstva (prohlížeč): nejvýš jedno video najednou

    # --- nastavení a stav -------------------------------------------------------------------------
    @property
    def db(self):
        return self.st.db

    def paused(self) -> bool:
        return bool(self.db.kv_get("catalog_paused", False))

    def gap(self) -> float:
        """Pauza mezi dotazy na stejný web: nastavení × režim výkonu × náhodný rozptyl ±30 %."""
        s = self.st.settings
        return float(s.get("catalog_gap") or 0) * PERF_MULT.get(s.get("perf_mode"), 1.0) * random.uniform(0.7, 1.3)

    def listing_busy(self) -> bool:
        return bool(self.db.query("select 1 from catalog_sources where status in ('queued','scanning') limit 1"))

    def allowed_now(self) -> bool:
        """Smí teď začít další práce? Ruční pozastavení a časový rozvrh (rozsah „catalog“)."""
        return not self.paused() and schedule.allowed(self.st.settings.all(), "catalog", db=self.db)

    def folder(self) -> Path:
        return catalog.thumbs_dir(self.st.data, self.st.settings)

    # --- výběr práce ------------------------------------------------------------------------------
    def excluded_hosts(self) -> set[str]:
        """Weby, na které se teď nesmí sahat: právě zpracovávané, ve vychlazení po dotazu nebo odložené po omezení."""
        now = time.monotonic()
        return set(self.active) | {h for h, t in self.next_at.items() if t > now} | {h for h, b in self.backoff.items() if b["until"] > now}

    def pick(self, excluded: set[str] | None = None) -> dict | None:
        """Další video k zjištění podrobností (v pořadí zdrojů a videí) z webu, který je právě volný."""
        excluded = self.excluded_hosts() if excluded is None else excluded
        sql = "select * from catalog_items where detail_state='pending' and state in ('new','queued')"
        args: list = []
        if excluded:
            sql += " and coalesce(host,'') not in (%s)" % ",".join("?" * len(excluded))
            args = sorted(excluded)
        rows = self.db.query(sql + " order by source_id, pos limit 1", args)
        return rows[0] if rows else None

    # --- zpracování jednoho videa -----------------------------------------------------------------
    async def process(self, item: dict) -> None:
        host = item.get("host") or ""
        try:
            info = await ytdlp.full_info(item["url"], detail_ctx(self.st), timeout=90)
        except ResolveError as e:
            self._on_error(item, e.kind, str(e))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("katalog: podrobnosti %s", item["id"])
            self._finish(item, "failed", f"{type(e).__name__}: {e}"[:300])
        else:
            await self._store(item, info)
            self.backoff.pop(host, None)
        finally:
            self.next_at[host] = time.monotonic() + self.gap()

    async def _store(self, item: dict, info: dict, expect: str = "pending") -> None:
        urls = best_thumbnails(info)
        title = info.get("title")
        channel = info.get("channel") or info.get("uploader")
        with self.db.conn() as c:
            n = c.execute(
                "update catalog_items set height=coalesce(?, height), size=coalesce(?, size), duration=coalesce(?, duration), "
                "title=coalesce(?, title), channel=coalesce(?, channel), thumb_url=coalesce(?, thumb_url), thumb_alts=coalesce(?, thumb_alts), "
                "anim_url=coalesce(?, anim_url), "
                "search=?, detail_state='done', detail_error=null, updated_at=? "
                "where id=? and detail_state=? and state in ('new','queued')",
                (ytdlp.best_height(info), ytdlp.size_estimate(info), info.get("duration"), title, channel, urls[0] if urls else None,
                 json.dumps(urls[1:1 + catalog.THUMB_ALTS_MAX]) if len(urls) > 1 else None, catalog.anim_candidate(info),
                 catalog.norm(f"{title or item['title'] or ''} {channel or item['channel'] or ''}"), time.time(), item["id"], expect)).rowcount
        if n and urls and urls[0] != item.get("thumb_url"):      # jiná (obvykle lepší) miniatura než ze seznamu: nahradit
            name = await asyncio.to_thread(download_thumb, self.folder(), item["id"], urls, thumbs.referer_of(item.get("url")))
            if name:
                with self.db.conn() as c:
                    c.execute("update catalog_items set thumb_file=?, updated_at=? where id=? and state in ('new','queued')", (name, time.time(), item["id"]))

    def _finish(self, item: dict, state: str, error: str | None, item_state: str | None = None) -> None:
        with self.db.conn() as c:
            c.execute("update catalog_items set detail_state=?, detail_error=?, state=coalesce(?, state), updated_at=? "
                      "where id=? and detail_state='pending'", (state, error, item_state, time.time(), item["id"]))

    def _on_error(self, item: dict, kind: str, msg: str) -> None:
        host = item.get("host") or ""
        low = msg.lower()
        if kind == "network":                                       # omezení dotazů, výpadek: web odložit, video zůstane čekat
            self._back_off(host, BACKOFF_FIRST, "omezení nebo výpadek webu: " + msg[:120])
        elif kind == "cookies" or "not a bot" in low or "confirm you" in low:
            self._back_off(host, BACKOFF_LOGIN, "web vyžaduje ověření nebo cookies: " + msg[:120])
        elif kind == "unsupported" and self.st.settings.get("catalog_slow_browser"):
            self._finish(item, "slow", None)                        # yt-dlp web nezná: podrobnosti později prohlížečem
        elif kind == "removed" or "private video" in low:
            self._finish(item, "failed", msg[:300], item_state="gone" if item.get("state") == "new" else None)
        else:                                                       # geo, drm, přihlášení k videu, přímý přenos, neznámé: jen u videa
            self._finish(item, "failed", f"{kind}: {msg}"[:300])

    def _back_off(self, host: str, first: float, reason: str) -> None:
        prev = self.backoff.get(host)
        delay = min(BACKOFF_MAX, max(first, (prev["delay"] * 2) if prev else first))
        self.backoff[host] = {"until": time.monotonic() + delay, "delay": delay, "reason": reason}
        log.warning("katalog: %s odloženo o %d s (%s)", host, delay, reason)

    # --- pomalá vrstva: prohlížeč --------------------------------------------------------------------
    def fast_work_left(self) -> bool:
        """Čeká ještě rychlá práce (podrobnosti přes yt-dlp) na webu, který není odložený? Pak pomalá vrstva počká."""
        now = time.monotonic()
        away = sorted(h for h, b in self.backoff.items() if b["until"] > now)
        sql = "select 1 from catalog_items where detail_state='pending' and state in ('new','queued')"
        if away:
            sql += " and coalesce(host,'') not in (%s)" % ",".join("?" * len(away))
        return bool(self.db.query(sql + " limit 1", away))

    def pick_slow(self, excluded: set[str] | None = None) -> dict | None:
        """Další video pro prohlížeč; odložený nebo právě vychlazovaný web se přeskočí (neblokuje ostatní)."""
        excluded = self.excluded_hosts() if excluded is None else excluded
        sql = "select * from catalog_items where detail_state='slow' and state in ('new','queued')"
        args: list = []
        if excluded:
            sql += " and coalesce(host,'') not in (%s)" % ",".join("?" * len(excluded))
            args = sorted(excluded)
        rows = self.db.query(sql + " order by source_id, pos limit 1", args)
        return rows[0] if rows else None

    def drop_slow(self) -> int:
        """Prohlížeč je vypnutý: čekající „pomalé“ položky se označí chybou (po zapnutí je vrátí „Zkusit znovu neúspěšné“)."""
        with self.db.conn() as c:
            return c.execute("update catalog_items set detail_state='failed', detail_error='vyžaduje prohlížeč (vypnuto v Nastavení › Katalog)', "
                             "updated_at=? where detail_state='slow'", (time.time(),)).rowcount

    async def process_slow(self, item: dict) -> None:
        """Jedno video prohlížečem: najde přehrávaný stream, rozlišení a miniaturu (stahování samo nic nestahuje)."""
        host = item.get("host") or ""
        try:
            sn = await sniffer.sniff(item["url"], detail_ctx(self.st))
        except ResolveError as e:
            if e.kind == "network":
                self._back_off(host, BACKOFF_FIRST, f"prohlížeč: {e}"[:140])
                self._finish_slow(item, "slow", None)              # zůstane čekat
            else:
                self._finish_slow(item, "failed", f"{e.kind}: {e}"[:300])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("katalog: pomalé podrobnosti %s", item["id"])
            self._finish_slow(item, "failed", f"{type(e).__name__}: {e}"[:300])
        else:
            cands = sn.get("candidates") or []
            if not cands:
                msg = "video je chráněné (DRM)" if sn.get("drm") else "na stránce se nepodařilo najít přehrávané video"
                self._finish_slow(item, "failed", msg)
            else:
                heights = [c.get("height") for c in cands if c.get("height")]
                info = {"title": item.get("title") or sn.get("title") or None, "thumbnail": sn.get("thumbnail"),
                        "height": max(heights) if heights else None,
                        "duration": next((c["duration"] for c in cands if c.get("duration")), None)}
                await self._store(item, info, expect="slow")
        finally:
            self.next_at[host] = time.monotonic() + self.gap()

    def _finish_slow(self, item: dict, state: str, error: str | None) -> None:
        with self.db.conn() as c:
            c.execute("update catalog_items set detail_state=?, detail_error=?, updated_at=? where id=? and detail_state='slow'",
                      (state, error, time.time(), item["id"]))

    # --- smyčky -----------------------------------------------------------------------------------
    async def run(self, stop: asyncio.Event) -> None:
        """Podrobnosti po jednom videu na web, souběžně nejvýš `MAX_HOSTS` webů; až po dokončení seznamů všech zdrojů."""
        while not stop.is_set():
            try:
                for h in [h for h, t in self.active.items() if t.done()]:
                    t = self.active.pop(h)
                    if not t.cancelled() and t.exception():
                        log.error("katalog: podrobnosti: %s", t.exception())
                item = None
                if len(self.active) < MAX_HOSTS and self.allowed_now() and not self.listing_busy():
                    item = await asyncio.to_thread(self.pick, self.excluded_hosts())      # množina se spočítá ve smyčce událostí
                if item is not None:
                    self.active[item.get("host") or ""] = asyncio.create_task(self.process(item))
                    continue
                if (not self.active and not self.slow_task and self.allowed_now() and not self.listing_busy()
                        and self.st.settings.get("catalog_slow_browser") and not await asyncio.to_thread(self.fast_work_left)):
                    slow = await asyncio.to_thread(self.pick_slow, self.excluded_hosts())   # jeden prohlížeč najednou, až po rychlé práci
                    if slow is not None:
                        self.slow_task = asyncio.create_task(self.process_slow(slow))
                if not self.st.settings.get("catalog_slow_browser"):
                    await asyncio.to_thread(self.drop_slow)
                if self.slow_task is not None and self.slow_task.done():
                    t, self.slow_task = self.slow_task, None
                    if not t.cancelled() and t.exception():
                        log.error("katalog: pomalé podrobnosti: %s", t.exception())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("katalog: podrobnosti, neočekávaná chyba")
                await _sleep(stop, 5)
                continue
            await _sleep(stop, 0.5)
        tasks = [*self.active.values(), *([self.slow_task] if self.slow_task else [])]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _thumb_one(self, row: dict) -> None:
        try:
            alts = json.loads(row.get("thumb_alts") or "[]")
        except ValueError:
            alts = []
        name = await asyncio.to_thread(download_thumb, self.folder(), row["id"], [row["thumb_url"], *[a for a in alts if isinstance(a, str)]],
                                       thumbs.referer_of(row.get("url")))
        with self.db.conn() as c:
            c.execute("update catalog_items set thumb_file=?, updated_at=? where id=? and thumb_file is null",
                      (name if name else "", time.time(), row["id"]))

    async def _anim_one(self, row: dict) -> None:
        max_bytes = int(float(self.st.settings.get("catalog_anim_max_mb") or 3) * 1024 * 1024)
        name = await asyncio.to_thread(download_anim, self.folder(), row["id"], row["anim_url"], max_bytes, thumbs.referer_of(row.get("url")))
        with self.db.conn() as c:
            n = c.execute("update catalog_items set anim_file=?, updated_at=? where id=? and anim_file is null and state in ('new','queued')",
                          (name if name else "", time.time(), row["id"])).rowcount
        if name and not n:                                        # položka mezitím zmizela: soubor je k ničemu
            catalog.remove_anim(self.folder(), name)

    async def thumbs_loop(self, stop: asyncio.Event) -> None:
        """Stahuje miniatury položkám, které ještě žádnou nemají (rychle, po dávkách; selhání se označí a nezkouší znovu)."""
        while not stop.is_set():
            try:
                rows = [] if not self.allowed_now() else await asyncio.to_thread(
                    self.db.query, "select id, url, thumb_url, thumb_alts from catalog_items where thumb_file is null and thumb_url is not null "
                    "and state in ('new','queued') order by source_id, pos limit ?", (THUMB_BATCH,))
                if rows:
                    await asyncio.gather(*(self._thumb_one(r) for r in rows))
                    await _sleep(stop, 0.2)
                    continue
                if self.st.settings.get("catalog_anim") and self.allowed_now() and not self.paused():     # animace až po všech miniaturách
                    arows = await asyncio.to_thread(
                        self.db.query, "select id, url, anim_url from catalog_items where anim_file is null and anim_url is not null "
                        "and state in ('new','queued') order by source_id, pos limit 2")
                    if arows:
                        await asyncio.gather(*(self._anim_one(r) for r in arows))
                        await _sleep(stop, 0.5)
                        continue
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("katalog: miniatury")
                await _sleep(stop, 5)
                continue
            await _sleep(stop, 3)

    # --- stav pro GUI -----------------------------------------------------------------------------
    def status(self) -> dict:
        r = self.db.query(
            "select sum(detail_state='pending') pending, sum(detail_state='slow') slow, sum(detail_state='done') done, sum(detail_state='failed') failed, "
            "sum(thumb_file is null and thumb_url is not null) thumbs_pending, sum(thumb_file = '') thumbs_failed "
            "from catalog_items where state in ('new','queued')")[0]
        now = time.monotonic()
        return {"pending": r["pending"] or 0, "slow": r["slow"] or 0, "done": r["done"] or 0, "failed": r["failed"] or 0,
                "thumbs_pending": r["thumbs_pending"] or 0, "thumbs_failed": r["thumbs_failed"] or 0,
                "paused": self.paused(), "waiting_for_lists": self.listing_busy(), "active_hosts": sorted(self.active),
                "backoff": [{"host": h, "seconds": int(b["until"] - now), "reason": b["reason"]} for h, b in sorted(self.backoff.items())
                            if b["until"] > now]}


async def _sleep(stop: asyncio.Event, sec: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), sec)
    except asyncio.TimeoutError:
        pass


def retry_failed(db, source: int | None = None) -> dict:
    """Zařadí znovu videa, kterým se podrobnosti nebo miniatura nepodařily zjistit."""
    where, args = "", []
    if source:
        where, args = " and source_id=?", [int(source)]
    with db.conn() as c:
        c.execute("begin immediate")
        d = c.execute("update catalog_items set detail_state='pending', detail_error=null where detail_state='failed' "
                      "and state in ('new','queued')" + where, args).rowcount
        t = c.execute("update catalog_items set thumb_file=null where thumb_file='' and state in ('new','queued')" + where, args).rowcount
        c.execute("commit")
    return {"details": d, "thumbs": t}


async def task(st, stop: asyncio.Event) -> None:
    w = getattr(st, "catalog_details", None) or DetailWorker(st)
    st.catalog_details = w
    await asyncio.gather(w.run(stop), w.thumbs_loop(stop))
