"""Katalog, etapa 2: podrobnosti videí (rozlišení, velikost, délka, nejlepší miniatura) a stahování miniatur.

Pořadí práce: nejdřív se dokončí seznamy všech zdrojů (`catalog.task`), teprve potom se zjišťují podrobnosti. Podrobnosti
se zjišťují po jednom videu s pauzou mezi dotazy na stejný web (`catalog_gap`, režim výkonu ji prodlužuje); různé weby
mohou běžet souběžně (nejvýš `MAX_HOSTS`). Omezení ze strany webu (HTTP 429, ověření „nejsem robot“) web odloží na delší
dobu, která se zdvojnásobuje; smazané nebo soukromé video se označí jen u sebe. Miniatury se stahují zvlášť a rychle.
Pomalá úroveň (prohlížeč u webů bez podpory yt-dlp) přijde s dalšími typy zdrojů.
"""
from __future__ import annotations

import asyncio
import contextlib
import collections
import copy
import dataclasses
import json
import logging
import random
import re
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import catalog, catalogpreview, netsafe, pagelist, schedule, storyboard, thumbs
from .resolvers import ResolveError, sniffer, ytdlp
from .util import host_key, is_rate_limited

log = logging.getLogger("viddown.catalogdetails")

MAX_HOSTS = 3                       # nejvýš tolik webů souběžně
BACKOFF_FIRST = 120.0               # první odložení webu po omezení (s); pak se zdvojnásobuje
BACKOFF_MAX = 7200.0
BACKOFF_LOGIN = 3600.0              # web vyžaduje přihlášení/ověření: zkusit až za hodinu
PERF_MULT = {"full": 1.0, "balanced": 2.0, "eco": 4.0}
THUMB_BATCH = 4
THUMB_GAP = 0.6                     # pauza mezi miniaturami/animacemi z téhož serveru (s)
MIN_GAP = 1.0                       # nejmenší pauza mezi dotazy na stejný web (s), i když je v nastavení méně
HOUR = 3600.0
RATE_RE = re.compile(r"\b429\b|too many requests|rate.?limit|slow down", re.I)      # omezení dotazů: čekat, ne měnit adresu
BLOCKED_RE = catalog.BLOCKED_RE
SRC_SCAN_PAGES = 30                 # nejvýš tolik stránek výpisu zdroje při hledání animací
THUMB_CANDIDATES = 10               # kolik kandidátů miniatury se zkusí, než se vzdá (největší varianty starším videím chybějí)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def detail_ctx(st, proxy: str | None = None):
    """Kontext pro zjišťování podrobností: vždy video v nejlepší kvalitě, bez ohledu na „jen zvuk“ v nastavení. `proxy` přepíše
    nastavenou proxy (záložní adresa)."""
    c = st.runner.ctx()
    settings = {**c.settings, "audio_only": False, "quality": "max"}
    if proxy:
        settings["proxy"] = proxy
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


def download_thumb(folder: Path, item_id: int, urls: list[str], referer: str | None = None, proxy: str | None = None) -> str | None:
    """Stáhne první použitelnou miniaturu ze seznamu a uloží ji jako `<id>.<přípona>` (starší soubor položky nahradí).
    Vrací název souboru, nebo None."""
    folder.mkdir(parents=True, exist_ok=True)
    for url in urls[:THUMB_CANDIDATES]:
        suffix = Path(url.split("?", 1)[0]).suffix.lower()
        ext = suffix if suffix in IMAGE_EXTS else ".jpg"
        tmp = folder / f"{item_id}{ext}.{uuid.uuid4().hex[:8]}.part"           # vlastní soubor pro každé stažení (souběh s podrobnostmi)
        try:
            if not thumbs.fetch(url, tmp, referer=referer, proxy=proxy) or not looks_like_image(tmp):
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


def download_anim(folder: Path, item_id: int, url: str, max_bytes: int, referer: str | None = None, proxy: str | None = None) -> str | None:
    """Stáhne animovaný náhled do složky miniatur jako `<id>.anim.<přípona>`. Adresa musí být veřejná (i po přesměrování), stahování
    má limit velikosti i celkového času. Soubor větší než `max_bytes` nebo s jiným obsahem (statický obrázek, HTML) se zahodí.
    Vrací název souboru, nebo None."""
    headers = {"User-Agent": thumbs.BROWSER_UA, "Referer": referer} if referer else {"User-Agent": thumbs.UA}
    try:
        got = netsafe.fetch_limited(url, headers, max_bytes, proxy)
    except Exception as e:  # noqa: BLE001 - cokoli z cizí adresy (i InvalidURL) nesmí zastavit smyčku animací
        log.debug("animace %s: %s", url, e)
        return None
    if got is None or got[0] != 200 or not got[2]:
        return None
    kind = anim_kind(got[2][:64])
    if not kind:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{item_id}.anim.{uuid.uuid4().hex[:8]}.part"
    try:
        tmp.write_bytes(got[2])
        final = folder / f"{item_id}.anim.{kind}"
        tmp.replace(final)
        for other in ("mp4", "webm", "gif", "webp"):                       # jediný soubor na položku
            if other != kind:
                (folder / f"{item_id}.anim.{other}").unlink(missing_ok=True)
        return final.name
    except OSError as e:
        log.debug("animace %s: %s", url, e)
        return None
    finally:
        tmp.unlink(missing_ok=True)


class DetailWorker:
    def __init__(self, st):
        self.st = st
        self.next_at: dict[str, float] = {}          # web -> čas (monotonic), kdy smí další dotaz
        self.backoff: dict[str, dict] = {}           # web -> {until, delay, reason}
        self.item_fails: dict[int, int] = {}         # video -> počet po sobě jdoucích chyb spojení; po třech se označí jako nedostupné
        self._stop_evt: asyncio.Event | None = None  # ukončení aplikace (nastavuje pages_loop)
        self.active: dict[str, asyncio.Task] = {}
        self._thumb_locks: dict[int, asyncio.Lock] = {}
        self.hits: dict[str, collections.deque] = {}  # web -> časy dotazů za poslední hodinu (strop dotazů)
        catalog.SCAN_GATE = self.scan_gate
        self.used_fallback: dict[str, float] = {}     # web -> kdy naposledy pomohla záložní proxy
        self.cdn_next: dict[str, float] = {}          # server miniatur -> nejdřív kdy další stažení
        self.src_scanned: dict[int, int] = {}        # zdroj -> nejvyšší číslo videa bez animace při prohledání jeho stránek (nová videa = znovu)
        self.page_hosts: set[str] = set()            # weby, na kterých právě běží sken stránky videa
        self.slow_task: asyncio.Task | None = None   # pomalá vrstva (prohlížeč): nejvýš jedno video najednou
        self.manual = False                          # ruční „Doplnit …“ obchází okno rozvrhu, dokud zbývá práce

    # --- nastavení a stav -------------------------------------------------------------------------
    @property
    def db(self):
        return self.st.db

    def paused(self) -> bool:
        return bool(self.db.kv_get("catalog_paused", False))

    def gap(self) -> float:
        """Pauza mezi dotazy na stejný web: nastavení × režim výkonu × náhodný rozptyl ±30 %."""
        s = self.st.settings
        base = max(MIN_GAP, float(s.get("catalog_gap") or 0)) * PERF_MULT.get(s.get("perf_mode"), 1.0)
        return base * random.uniform(0.7, 1.3)

    # --- slušnost k cizím serverům: strop dotazů za hodinu a záložní proxy ------------------------------
    def scan_gate(self, host: str) -> bool:
        """Další stránka seznamu: smí se, jen když web nepřekročil hodinový strop; dotaz se započítá."""
        if self.over_budget(host):
            return False
        self.note_request(host)
        return True

    def note_request(self, host: str) -> None:
        q = self.hits.setdefault(host, collections.deque())
        now = time.monotonic()
        while q and q[0] < now - HOUR:                                  # starší dotazy se zahodí už při zápisu (jinak by seznam rostl bez mezí)
            q.popleft()
        q.append(now)

    def over_budget(self, host: str) -> bool:
        limit = int(self.st.settings.get("catalog_hour_limit") or 0)
        q = self.hits.get(host)
        if not limit or not q:
            return False
        cutoff = time.monotonic() - HOUR
        while q and q[0] < cutoff:
            q.popleft()
        return len(q) >= limit

    def limited_hosts(self) -> set[str]:
        """Weby přes hodinový strop dotazů a weby, které fronta pozastavila po omezení (pauza webu je společná)."""
        out = {h for h in list(self.hits) if self.over_budget(h)}
        rn = getattr(self.st, "runner", None)
        if rn is not None and getattr(rn, "host_pause", None):
            now = time.time()
            paused = {k for k, v in rn.host_pause.items() if v.get("until", 0) > now}
            if paused:
                out |= {h for h in self._known_hosts() if host_key("https://" + h + "/") in paused}
        return out

    def _known_hosts(self) -> set[str]:
        """Weby položek, na které katalog ještě čeká (pro převod pauzy fronty, která pracuje s `host_key`)."""
        try:
            return {r["host"] for r in self.db.query("select distinct host from catalog_items where host is not null "
                                                     "and detail_state in ('pending','slow') and state in ('new','queued')")}
        except Exception:  # noqa: BLE001
            return set()

    def fallback_proxy(self) -> str | None:
        fb = str(self.st.settings.get("catalog_proxy_fallback") or "").strip()
        return fb if fb and fb != (self.st.settings.get("proxy") or "") else None

    @staticmethod
    def fallback_worthy(msg: str) -> bool:
        """Chyba spojení nebo serveru, kde může pomoci jiná adresa; omezení (429) ne: tam se čeká."""
        low = (msg or "").lower()
        return not RATE_RE.search(low) and bool(re.search(r"timed out|timeout|connection|connect|reset|refused|unreachable|http 5|se nepodařilo načíst|failed to perform|temporary failure|network", low))

    async def _fetch_page(self, url: str, host: str, public_only: bool) -> tuple[str, str]:
        """`pagelist.fetch` se započtením do stropu a jedním pokusem přes záložní proxy po chybě spojení (po pauze, ne při 429)."""
        self.note_request(host)
        try:
            return await pagelist.fetch(url, self.st.settings.all(), public_only=public_only)
        except pagelist.PageError as e:
            fb = self.fallback_proxy()
            if not (fb and self.fallback_worthy(str(e))):
                raise
            await asyncio.sleep(self.gap())
            self.note_request(host)
            try:
                res = await pagelist.fetch(url, {**self.st.settings.all(), "proxy": fb}, public_only=public_only)
            except pagelist.PageError as e2:
                raise pagelist.PageError(f"{e}; přes záložní proxy: {e2}") from e2
            self.used_fallback[host] = time.monotonic()
            return res

    def listing_busy(self) -> bool:
        return bool(self.db.query("select 1 from catalog_sources where status in ('queued','scanning') limit 1"))

    def allowed_now(self) -> bool:
        """Smí teď začít další práce? Ruční pozastavení a časový rozvrh (rozsah „catalog“). Ruční „Doplnit …“ rozvrh obejde,
        dokud zbývají položky k doplnění."""
        if self.paused():
            return False
        if self.manual and not self._manual_left():
            self.manual = False                              # ruční doplnění dokončeno: dál platí jen rozvrh
        if schedule.allowed(self.st.settings.all(), "catalog", db=self.db):
            return True
        return self.manual

    def request_manual(self) -> None:
        """Tlačítka „Doplnit animace“ a „Doplnit data“ spustí doplnění hned, i mimo okno rozvrhu (do vyřízení položek)."""
        self.manual = True

    def _manual_left(self) -> bool:
        return bool(self.db.query("select 1 from catalog_items where state in ('new','queued') and detail_state='pending' limit 1")) \
            or bool(self.pending_anims(1))

    def folder(self) -> Path:
        return catalog.thumbs_dir(self.st.data, self.st.settings)

    async def _stored(self, fn, *args):
        """Stažení do složky platné při spuštění. Když se složka mezitím změnila v nastavení, soubor se přesune do nové
        (jinak by databáze odkazovala na soubor, který v nové složce chybí)."""
        folder = self.folder()
        name = await asyncio.to_thread(fn, folder, *args)
        return await asyncio.to_thread(self._move_to_current, folder, name) if name else None

    def _move_to_current(self, used: Path, name: str) -> str | None:
        cur = self.folder()
        if cur == used:
            return name
        try:
            cur.mkdir(parents=True, exist_ok=True)
            shutil.move(str(used / name), str(cur / name))
            return name
        except OSError as e:
            log.warning("katalog: soubor %s se nepodařilo přesunout do nové složky: %s", name, e)
            return None

    # --- výběr práce ------------------------------------------------------------------------------
    def excluded_hosts(self) -> set[str]:
        """Weby, na které se teď nesmí sahat: právě zpracovávané, ve vychlazení po dotazu nebo odložené po omezení."""
        now = time.monotonic()
        return (set(self.active) | self.page_hosts | {h for h, t in list(self.next_at.items()) if t > now} | {h for h, b in list(self.backoff.items()) if b["until"] > now}
                | self.limited_hosts())

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
        if not netsafe.literal_ok(item.get("url") or ""):                 # adresa z cizího seznamu nesmí mířit do místní sítě
            self._finish(item, "failed", "adresa míří mimo veřejný internet")
            return
        self.note_request(host)
        try:
            try:
                info = await ytdlp.full_info(item["url"], detail_ctx(self.st), timeout=90)
            except ResolveError as e:
                fb = self.fallback_proxy()
                if not (e.kind == "network" and fb and self.fallback_worthy(str(e))):
                    raise
                await asyncio.sleep(self.gap())                           # pauza i před druhým pokusem; omezení (429) se touto cestou neobchází
                self.note_request(host)
                try:
                    info = await ytdlp.full_info(item["url"], detail_ctx(self.st, proxy=fb), timeout=90)
                except ResolveError as e2:
                    raise ResolveError(f"{e}; přes záložní proxy: {e2}", e2.kind) from e2
                self.used_fallback[host] = time.monotonic()
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
        n = await asyncio.to_thread(_store_details, self.db, item, info, expect, urls)
        if n and urls and urls[0] != item.get("thumb_url"):      # jiná (obvykle lepší) miniatura než ze seznamu: nahradit
            async with self._thumb_lock(item["id"]):
                name = await self._stored(download_thumb, item["id"], urls, thumbs.referer_of(item.get("url")), self.proxy())
            if name:
                with self.db.conn() as c:
                    c.execute("update catalog_items set thumb_file=?, updated_at=? where id=? and state in ('new','queued')", (name, time.time(), item["id"]))

    def _video_failed_again(self, item: dict) -> bool:
        """Počítá chyby spojení u jednoho videa. Vrací True, až když jich je tři v řadě (pak se video označí jako selhané)."""
        n = self.item_fails.get(item["id"], 0) + 1
        self.item_fails[item["id"]] = n
        return n >= 3

    def _finish(self, item: dict, state: str, error: str | None, item_state: str | None = None) -> None:
        self.item_fails.pop(item["id"], None)
        with self.db.conn() as c:
            c.execute("update catalog_items set detail_state=?, detail_error=?, state=case when ? is not null and state='new' then ? else state end, updated_at=? "
                      "where id=? and detail_state='pending'", (state, error, item_state, item_state, time.time(), item["id"]))

    def _on_error(self, item: dict, kind: str, msg: str) -> None:
        host = item.get("host") or ""
        low = msg.lower()
        note = getattr(getattr(self.st, "runner", None), "note_host_limit", None)
        if is_rate_limited(msg) and note is not None:
            note("https://" + host + "/", msg)                                # omezení webu platí i pro frontu a odběry
        if kind == "network" or is_rate_limited(msg):               # omezení dotazů, výpadek: web odložit, video zůstane čekat
            self._back_off(host, BACKOFF_FIRST, "omezení nebo výpadek webu: " + msg[:120])
            if kind == "network" and self._video_failed_again(item):   # jedno problémové video nesmí blokovat zbytek webu donekonečna
                self._finish(item, "failed", "opakovaně nedostupné: " + msg[:200])
        elif kind == "cookies" or "not a bot" in low or re.search(r"confirm you(?:'|’)?(?:re| are) not", low):   # „confirm your age“ je chyba jednoho videa, ne webu
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
        away = sorted(h for h, b in list(self.backoff.items()) if b["until"] > now)
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
        if not await asyncio.to_thread(netsafe.host_ok, item["url"]):          # prohlížeč ani ffmpeg nesmí z cizí stránky na vnitřní síť
            self._finish_slow(item, "failed", "adresa vede do vnitřní sítě")
            return
        self.note_request(host)
        try:
            try:
                sn = await sniffer.sniff(item["url"], detail_ctx(self.st))
            except ResolveError as e0:
                fb = self.fallback_proxy()
                if not (e0.kind == "network" and fb and self.fallback_worthy(str(e0))):
                    raise
                await asyncio.sleep(self.gap())
                self.note_request(host)
                sn = await sniffer.sniff(item["url"], detail_ctx(self.st, proxy=fb))
                self.used_fallback[host] = time.monotonic()
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
                for h in [h for h, t in list(self.active.items()) if t.done()]:
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
        try:
            async with self._thumb_lock(row["id"]):                    # souběh se `_store` (lepší miniatura z podrobností) by smazal soubor druhého
                cur = self.db.query("select thumb_file from catalog_items where id=?", (row["id"],))
                if not cur or cur[0]["thumb_file"] is not None:         # mezitím ji uložil `_store` nebo položka zmizela
                    return
                name = await self._stored(download_thumb, row["id"], [row["thumb_url"], *[a for a in alts if isinstance(a, str)]],
                                               thumbs.referer_of(row.get("url")), self.proxy())
        except OSError as e:                                             # výpadek zápisu (třeba NAS): nejde o vadnou miniaturu, zůstane čekat na další pokus
            log.warning("katalog: miniaturu %s nejde uložit (%s), zkusí se znovu", row["id"], e)
            return
        except Exception:  # noqa: BLE001 - chyba jedné miniatury nesmí zastavit smyčku (jinak by se pokaždé zkoušela znovu ta samá)
            log.exception("katalog: miniatura %s", row["id"])
            name = None
        await asyncio.to_thread(_set_thumb_file, self.db, row["id"], name)

    async def _cdn_wait(self, url: str | None) -> None:
        """Pauza mezi dvěma staženími ze stejného serveru miniatur nebo animací (`THUMB_GAP` ± rozptyl)."""
        try:
            host = (urlsplit(url or "").hostname or "").lower() if not str(url or "").startswith("sb:") else "storyboard"
        except ValueError:
            host = ""
        now = time.monotonic()
        wait = self.cdn_next.get(host, 0.0) - now
        self.cdn_next[host] = max(now, self.cdn_next.get(host, 0.0)) + THUMB_GAP * random.uniform(0.7, 1.3)
        if len(self.cdn_next) > 500:
            self.cdn_next = {h: t for h, t in self.cdn_next.items() if t > now}
        if wait > 0:
            await asyncio.sleep(wait)

    def _thumb_lock(self, item_id: int) -> asyncio.Lock:
        if len(self._thumb_locks) > 2000:                              # nepoužívané zámky se uklidí
            self._thumb_locks = {k: v for k, v in self._thumb_locks.items() if v.locked()}
        return self._thumb_locks.setdefault(item_id, asyncio.Lock())

    def pending_anims(self, limit: int) -> list[dict]:
        """Animace čekající na stažení; storyboardy se přeskočí, dokud chybí ffmpeg (jinak by se natrvalo označily jako nepodařené)."""
        sql = ("select id, url, anim_url from catalog_items where anim_file is null and anim_url is not null and anim_url != '' "
               "and state in ('new','queued')")
        if not self.ffmpeg():
            sql += " and anim_url not like 'sb:%'"
        return self.db.query(sql + " order by source_id, pos limit ?", (limit,))

    def proxy(self) -> str | None:
        return self.st.settings.get("proxy") or None

    def ffmpeg(self) -> str | None:
        """Cesta k ffmpeg ze správce enginů (jinak ffmpeg v PATH)."""
        try:
            p = self.st.runner.ctx().engines.get("ffmpeg").bin_path()
        except Exception:  # noqa: BLE001
            p = None
        return str(p) if p else shutil.which("ffmpeg")

    async def _anim_one(self, row: dict) -> None:
        max_bytes = int(float(self.st.settings.get("catalog_anim_max_mb") or 5) * 1024 * 1024)
        referer = thumbs.referer_of(row.get("url"))
        try:
            if storyboard.is_spec(row["anim_url"]):                   # storyboard: obrázky se složí ffmpegem do krátkého MP4
                name = await self._stored(storyboard.build, row["id"], row["anim_url"], self.ffmpeg(), max_bytes, referer, self.proxy())
            else:
                name = await self._stored(download_anim, row["id"], row["anim_url"], max_bytes, referer, self.proxy())
        except Exception:  # noqa: BLE001 - jedna vadná animace nesmí zastavit všechny ostatní
            log.exception("katalog: animace %s", row["id"])
            name = None
        n = await asyncio.to_thread(_set_anim_file, self.db, row["id"], name)
        if name and not n:                                        # položka mezitím zmizela: soubor je k ničemu
            catalog.remove_anim(self.folder(), name)

    # --- animace ze stránky videa (zdroj C): nejnižší priorita, po jednom videu na web ------------------------
    def pages_ready(self) -> bool:
        """Smí se teď hledat náhled na stránkách videí? Zapnuté animace i hledání na stránkách, mimo pauzu, v rozvrhu, po dokončení
        seznamů, rychlé práce a stahování nalezených animací."""
        s = self.st.settings
        if not (s.get("catalog_anim") and s.get("catalog_anim_pages")) or not self.allowed_now() or self.listing_busy() or self.fast_work_left():
            return False
        return not self.pending_anims(1)

    def pick_page_scan(self, excluded: set[str] | None = None) -> dict | None:
        excluded = self.excluded_hosts() if excluded is None else excluded
        sql = "select * from catalog_items where anim_url is null and detail_state='done' and state in ('new','queued')"
        args: list = []
        if excluded:
            sql += " and coalesce(host,'') not in (%s)" % ",".join("?" * len(excluded))
            args = sorted(excluded)
        rows = self.db.query(sql + " order by source_id, pos limit 1", args)
        return rows[0] if rows else None

    def _mark_anim(self, item: dict, value: str) -> None:
        with self.db.conn() as c:
            c.execute("update catalog_items set anim_url=?, updated_at=? where id=? and anim_url is null and state in ('new','queued')",
                      (value, time.time(), item["id"]))

    async def process_page_scan(self, item: dict) -> None:
        """Stáhne stránku videa a najde na ní náhledový klip nebo animaci; nic nenalezeno = `anim_url=''` (znovu až „Doplnit“)."""
        host = item.get("host") or ""
        if not await asyncio.to_thread(netsafe.host_ok, item["url"]):          # adresa videa pochází z cizí stránky: do vnitřní sítě se nesahá
            self._mark_anim(item, "")
            return
        self.page_hosts.add(host)                                      # během skenu na tento web nesmí sahat ani worker podrobností
        backoff_before = self.backoff.get(host)
        try:
            text, final = await self._fetch_page(item["url"], host, True)
        except pagelist.PageError as e:
            msg = str(e)
            if "HTTP 429" in msg or "HTTP 5" in msg or "se nepodařilo načíst" in msg:       # omezení nebo výpadek: web odložit, video zůstane čekat
                self._back_off(host, BACKOFF_FIRST, "stránka videa: " + msg[:120])
            else:
                self._mark_anim(item, "")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("katalog: stránka videa %s", item["id"])
            self._mark_anim(item, "")
        else:
            found = await asyncio.to_thread(catalogpreview.find_preview, text, final)      # regexy nad 1,5 MB HTML nesmí blokovat smyčku událostí
            self._mark_anim(item, found or "")
            if self.backoff.get(host) is backoff_before:                # odklad, který mezitím nastavil jiný worker, se nemaže
                self.backoff.pop(host, None)
        finally:
            self.page_hosts.discard(host)
            self.next_at[host] = time.monotonic() + self.gap()

    # --- animace ze stránek zdroje (výpis videí): jedna stránka = animace desítek videí, proto dřív než stránky videí ---------
    def source_scan_ready(self) -> bool:
        """Smí se teď hledat animace na stránkách zdrojů? Jako `pages_ready`, ale nečeká na rychlou práci ani na stahování animací: pár
        dotazů na výpis nahradí stovky dotazů na podrobnosti a stránky videí, takže má jít první."""
        s = self.st.settings
        return bool(s.get("catalog_anim") and s.get("catalog_anim_pages")) and self.allowed_now() and not self.listing_busy()

    def scan_blocked_hosts(self) -> set[str]:
        """Weby, kterým se prohledání zdroje odloží: jen odložené po omezení a ty, kde už jiný sken stránky běží. Pauza mezi dotazy
        podrobností (`next_at`) se nezohledňuje, jinak by nepřetržitá práce na podrobnostech hledání animací nikdy nepustila."""
        now = time.monotonic()
        return set(self.page_hosts) | {h for h, b in list(self.backoff.items()) if b["until"] > now} | self.limited_hosts()

    def pick_source_scan(self, excluded: set[str]) -> dict | None:
        for r in self.db.query(
                "select s.id, s.url, (select max(i.id) from catalog_items i where i.source_id=s.id and i.anim_url is null "
                "and i.state in ('new','queued')) top from catalog_sources s where s.status='done' and top is not null order by s.id"):
            if self.src_scanned.get(r["id"], 0) >= r["top"]:
                continue
            if catalog.domain(r["url"]) in excluded:
                continue
            return r
        return None

    async def process_source_scan(self, src: dict) -> None:
        """Projde stránku zdroje a jeho další stránky (nejvýš `SRC_SCAN_PAGES`, s pauzou mezi nimi), najde náhledové klipy a spáruje
        je s videi podle společného čísla v adrese. Spárovaným videím uloží adresu animace (stáhne se hned po miniaturách, adresy bývají
        podepsané a brzy vyprší), videím, která na prohlédnutých stránkách jsou, ale klip nemají, `''`. Ostatní zůstanou pro hledání na
        stránkách videí."""
        sid, host = src["id"], catalog.domain(src["url"])
        self.src_scanned[sid] = src["top"]
        self.page_hosts.add(host)
        url, page_no, visited, failed, rd = src["url"], 1, set(), False, None
        backoff_before = self.backoff.get(host)
        stack = contextlib.AsyncExitStack()
        try:
            while url and url not in visited and page_no <= SRC_SCAN_PAGES and not (self._stop_evt and self._stop_evt.is_set()):
                visited.add(url)
                if page_no > 1 and not await asyncio.to_thread(netsafe.host_ok, url):      # odkaz na další stránku je z cizího HTML
                    break
                try:
                    if rd is not None:                                  # web už jednou odmítl prostý dotaz: dál jen prohlížečem
                        text, final = await rd.render(url, scrolls=1)
                    else:
                        text, final = await self._fetch_page(url, host, page_no > 1)
                except pagelist.PageError as e:
                    msg = str(e)
                    if "HTTP 429" in msg or "HTTP 5" in msg or "se nepodařilo načíst" in msg:
                        self.src_scanned.pop(sid, None)                  # omezení nebo výpadek: zkusit později
                        self._back_off(host, BACKOFF_FIRST, "stránka zdroje: " + msg[:120])
                        failed = True
                        break
                    if not (BLOCKED_RE.search(msg) and self.st.settings.get("catalog_slow_browser")):
                        break
                    # web odmítl prostý dotaz (typicky 403/410 podle otisku spojení), ale prohlížeč pustí: vykreslí se Chromiem
                    try:
                        rd = await stack.enter_async_context(sniffer.Renderer(self.st.runner.ctx()))
                        text, final = await rd.render(url, scrolls=1)
                    except ResolveError as e2:
                        log.warning("katalog: stránku zdroje %s nelze vykreslit prohlížečem: %s", sid, str(e2)[:150])
                        break
                except ResolveError as e:
                    log.warning("katalog: stránku zdroje %s nelze vykreslit prohlížečem: %s", sid, str(e)[:150])
                    break
                items = await asyncio.to_thread(
                    self.db.query, "select id, url, thumb_url from catalog_items where source_id=? and anim_url is null "
                    "and state in ('new','queued')", (sid,))
                if not items:
                    break
                others = await asyncio.to_thread(
                    self.db.query, "select id, url, thumb_url from catalog_items where source_id=? and anim_url is not null "
                    "and state in ('new','queued')", (sid,))
                found, seen, ncand = await asyncio.to_thread(catalogpreview.match_listing, text, final, items, others)
                if not ncand and page_no == 1:
                    break                                               # stránka žádné náhledy nenabízí (např. YouTube): nic neznačit
                now = time.time()
                await asyncio.to_thread(_write_listing_anims, self.db, found, seen, now)
                if not seen:
                    break                                               # na stránce není žádné naše video: další už nepomůže
                if len(seen) >= len(items):
                    break                                               # všechna videa vyřízena
                url = await asyncio.to_thread(catalogpreview.next_page_url, text, final, page_no)
                page_no += 1
                if url:
                    await asyncio.sleep(self.gap())
            if not failed and self.backoff.get(host) is backoff_before:   # odklad, který mezitím nastavil worker podrobností, se nemaže
                self.backoff.pop(host, None)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("katalog: stránky zdroje %s", sid)
        finally:
            await stack.aclose()
            self.page_hosts.discard(host)
            self.next_at[host] = time.monotonic() + self.gap()

    async def pages_loop(self, stop: asyncio.Event) -> None:
        self._stop_evt = stop                                           # dlouhé zjišťování zdroje se zastaví při ukončení aplikace
        while not stop.is_set():
            try:
                if await asyncio.to_thread(self.source_scan_ready):
                    src = await asyncio.to_thread(self.pick_source_scan, self.scan_blocked_hosts())
                    if src is not None:
                        await self.process_source_scan(src)
                        continue
                if await asyncio.to_thread(self.pages_ready):
                    item = await asyncio.to_thread(self.pick_page_scan, self.excluded_hosts())
                    if item is not None:
                        await self.process_page_scan(item)
                        continue
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("katalog: hledání náhledů na stránkách")
                await _sleep(stop, 5)
                continue
            await _sleep(stop, 2)

    async def folder_ready(self) -> bool:
        """Je složka miniatur dostupná k zápisu? Kontrola ve vlákně s limitem a s pamětí na 30 s (odpojený nebo zaseknutý NAS)."""
        now = time.monotonic()
        if now < getattr(self, "_folder_until", 0.0):
            return getattr(self, "_folder_ok", True)

        def probe() -> bool:
            f = self.folder()
            f.mkdir(parents=True, exist_ok=True)
            return f.is_dir()
        try:
            ok = await asyncio.wait_for(asyncio.to_thread(probe), 6.0)
        except (asyncio.TimeoutError, OSError):
            ok = False
        if not ok and getattr(self, "_folder_ok", True):
            log.warning("katalog: složka miniatur není dostupná, miniatury a animace čekají")
        self._folder_ok, self._folder_until = ok, now + 30.0
        return ok

    async def thumbs_loop(self, stop: asyncio.Event) -> None:
        """Stahuje miniatury položkám, které ještě žádnou nemají (rychle, po dávkách; selhání se označí a nezkouší znovu)."""
        while not stop.is_set():
            try:
                rows = [] if not self.allowed_now() or not await self.folder_ready() else await asyncio.to_thread(
                    self.db.query, "select id, url, thumb_url, thumb_alts from catalog_items where thumb_file is null and thumb_url is not null "
                    "and state in ('new','queued') order by source_id, pos limit ?", (THUMB_BATCH,))
                if rows:
                    for r in rows:                                          # po jedné, s pauzou mezi dotazy na stejný server (nezahlcovat CDN)
                        if stop.is_set():
                            break
                        await self._cdn_wait(r.get("thumb_url"))
                        await self._thumb_one(r)
                    continue
                if self.st.settings.get("catalog_anim") and self.allowed_now() and not self.paused() and await self.folder_ready():     # animace až po všech miniaturách
                    arows = await asyncio.to_thread(self.pending_anims, 2)
                    if arows:
                        for r in arows:
                            if stop.is_set():
                                break
                            await self._cdn_wait(r.get("anim_url"))
                            await self._anim_one(r)
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
            "sum(thumb_file is null and thumb_url is not null) thumbs_pending, sum(thumb_file = '') thumbs_failed, "
            "sum(anim_file is null and anim_url is not null and anim_url != '') anim_pending, sum(anim_url is null and detail_state='done') anim_scan, sum(anim_file is not null and anim_file != '') anim_have, "
            "sum(anim_file = '') anim_failed, sum(detail_state='done' and published_at is null) no_date, sum(published_at > 0) have_date "
            "from catalog_items where state in ('new','queued')")[0]
        now = time.monotonic()
        return {"pending": r["pending"] or 0, "slow": r["slow"] or 0, "done": r["done"] or 0, "failed": r["failed"] or 0,
                "thumbs_pending": r["thumbs_pending"] or 0, "thumbs_failed": r["thumbs_failed"] or 0,
                "anim_pending": r["anim_pending"] or 0, "anim_scan": r["anim_scan"] or 0, "anim_have": r["anim_have"] or 0, "anim_failed": r["anim_failed"] or 0, "no_date": r["no_date"] or 0, "have_date": r["have_date"] or 0,
                "paused": self.paused(), "waiting_for_lists": self.listing_busy(), "active_hosts": sorted(self.active),
                "limited": sorted(self.limited_hosts()),
                "fallback_hosts": sorted(h for h, t in self.used_fallback.items() if now - t < 600),
                "backoff": [{"host": h, "seconds": int(b["until"] - now), "reason": b["reason"]} for h, b in sorted(list(self.backoff.items()))
                            if b["until"] > now]}


def _store_details(db, item: dict, info: dict, expect: str, urls: list) -> int:
    """Zápis podrobností videa (běží ve vlákně, ne ve smyčce událostí)."""
    title = info.get("title")
    channel = info.get("channel") or info.get("uploader")
    with db.conn() as c:
        return c.execute(
            "update catalog_items set height=coalesce(?, height), size=coalesce(?, size), duration=coalesce(?, duration), "
            "title=coalesce(?, title), channel=coalesce(?, channel), thumb_url=coalesce(?, thumb_url), thumb_alts=coalesce(?, thumb_alts), "
            "anim_url=coalesce(?, anim_url), published_at=coalesce(?, published_at, 0), "
            "search=?, detail_state='done', detail_error=null, updated_at=? "
            "where id=? and detail_state=? and state in ('new','queued')",
            (ytdlp.best_height(info), ytdlp.size_estimate(info), info.get("duration"), title, channel, urls[0] if urls else None,
             json.dumps(urls[1:1 + catalog.THUMB_ALTS_MAX]) if len(urls) > 1 else None, catalog.anim_source(info), catalog.published_ts(info),
             catalog.norm(f"{title or item['title'] or ''} {channel or item['channel'] or ''}"), time.time(), item["id"], expect)).rowcount


def _set_thumb_file(db, item_id: int, name: str | None) -> None:
    with db.conn() as c:
        c.execute("update catalog_items set thumb_file=?, updated_at=? where id=? and thumb_file is null",
                  (name if name else "", time.time(), item_id))


def _set_anim_file(db, item_id: int, name: str | None) -> int:
    with db.conn() as c:
        return c.execute("update catalog_items set anim_file=?, updated_at=? where id=? and anim_file is null and state in ('new','queued')",
                         (name if name else "", time.time(), item_id)).rowcount


def _write_listing_anims(db, found: dict, seen: set, now: float) -> None:
    """Zápis adres animací z výpisu zdroje (běží ve vlákně)."""
    with db.conn() as c:
        for iid, u in found.items():
            c.execute("update catalog_items set anim_url=?, updated_at=? where id=? and anim_url is null and state in ('new','queued')", (u, now, iid))
        if len(found) * 2 >= len(seen):                           # klipy jsou na výpisu běžné: videa bez klipu ho opravdu nemají
            for iid in seen - set(found):                         # jinak je to nejspíš chyba párování: videa zůstanou pro hledání na jejich stránce
                c.execute("update catalog_items set anim_url='', updated_at=? where id=? and anim_url is null and state in ('new','queued')", (now, iid))


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


def refill_anims(db, source: int | None = None) -> dict:
    """„Doplnit animace“ (viditelná videa): (1) videím, kde se na stránce videa nic nenašlo (`anim_url=''`), vrátí hledání na stránce;
    (2) videím, kterým se animace nepodařilo stáhnout (nad limit, vypršelá adresa), zapomene adresu i pokus a znovu zjistí podrobnosti
    (adresa se získá čerstvá); (3) videím bez adresy animace znovu zjistí podrobnosti (u starších se adresa neukládala; zjistí se
    spolu s ostatními podrobnostmi, po jednom na web s pauzou). Vrací počty {"details", "retry", "pages"}."""
    where, args = "", []
    if source:
        where, args = " and source_id=?", [int(source)]
    vis = " and state in ('new','queued')"
    with db.conn() as c:
        c.execute("begin immediate")
        d = c.execute("update catalog_items set detail_state='pending', detail_error=null where detail_state='done' "
                      "and anim_url is null and anim_file is null" + vis + where, args).rowcount
        g = c.execute("update catalog_items set anim_url=null where anim_url='' and anim_file is null and detail_state='done'" + vis + where, args).rowcount
        r = c.execute("update catalog_items set anim_file=null, anim_url=null, detail_state='pending', detail_error=null "
                      "where anim_file='' and detail_state='done'" + vis + where, args).rowcount
        c.execute("commit")
    return {"details": d, "retry": r, "pages": g}


def refill_dates(db, source: int | None = None) -> dict:
    """„Doplnit data“: viditelným videím bez zjištěného data zveřejnění znovu zjistí podrobnosti (po jednom na web s pauzou).
    Videa, kde web datum nenabízí (`published_at=0`), se neopakují. Vrací {"details": počet}."""
    where, args = "", []
    if source:
        where, args = " and source_id=?", [int(source)]
    with db.conn() as c:
        n = c.execute("update catalog_items set detail_state='pending', detail_error=null where detail_state='done' and published_at is null "
                      "and state in ('new','queued')" + where, args).rowcount
    return {"details": n}


async def task(st, stop: asyncio.Event) -> None:
    w = getattr(st, "catalog_details", None) or DetailWorker(st)
    st.catalog_details = w
    await asyncio.gather(w.run(stop), w.thumbs_loop(stop), w.pages_loop(stop))
