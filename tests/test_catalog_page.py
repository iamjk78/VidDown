"""Katalog, etapa 5: zdroje typu „stránka“ (rychlá vrstva z HTML, pomalá přes prohlížeč), pomalé podrobnosti, automatické hledání."""
import asyncio
import time
from types import SimpleNamespace

import pytest

from tests.test_catalog import fake, scan  # noqa: F401
from tests.test_runner import rt  # noqa: F401
from tests.test_catalog_details import St as DSt, images, info, rows, run_until, states  # noqa: F401
from viddown import catalog, catalogdetails as cd, pagelist
from viddown.config import Settings
from viddown.db import DB
from viddown.resolvers import ResolveError

@pytest.fixture(autouse=True)
def no_dns_for_pages(monkeypatch):
    """Adresy videí se před prohlížečem ověřují včetně DNS; zkoušky běží bez sítě, proto jen kontrola zápisu adresy."""
    monkeypatch.setattr(cd.netsafe, "host_ok", cd.netsafe.literal_ok)


UNSUP = ResolveError("Unsupported URL: https://web.example/porad", "unsupported")
BASE = "https://web.example/porad"


def page_html(names, nxt=None, pager=()):
    links = "".join(f'<a href="/dily/{n}">Díl {n} 8.11.2026</a>' for n in names)
    nav = "".join(f'<a href="/porad?pg={p}">{p}</a>' for p in pager)
    return f"<html><head><title>Pořad Test</title></head><body>{links}{nav}</body></html>"


class PSt:
    def __init__(self, data, **settings):
        self.data = data
        self.db = DB(data / "viddown.db")
        self.settings = Settings()
        self.settings.update({"catalog_gap": 0, **settings})
        self.runner = SimpleNamespace(ctx=lambda: SimpleNamespace(settings=self.settings.all()))


@pytest.fixture
def st_(data):
    return DSt(data)


@pytest.fixture
def pst(data):
    return PSt(data)


@pytest.fixture
def web(monkeypatch):
    """Podvržený web: pagelist.fetch podle adresy, vykreslení prohlížečem a sniffer."""
    pages, rendered, fetched = {}, {}, []

    async def fetch(url, settings=None, timeout=30):
        fetched.append(url)
        a = pages[url]
        if isinstance(a, Exception):
            raise a
        return a, url

    class FakeRenderer:
        """Jeden „prohlížeč“ pro všechny stránky: eviduje počet spuštění."""
        def __init__(self, ctx):
            pass

        async def __aenter__(self):
            rendered["launches"] = rendered.get("launches", 0) + 1
            return self

        async def __aexit__(self, *exc):
            rendered["closed"] = rendered.get("closed", 0) + 1

        async def render(self, url, scrolls=6):
            rendered.setdefault("calls", []).append(url)
            return rendered[url], url
    monkeypatch.setattr(pagelist, "fetch", fetch)
    monkeypatch.setattr(catalog.sniffer, "Renderer", FakeRenderer)
    monkeypatch.setattr(catalog.pagelist, "fetch", fetch)

    async def nosleep(_):
        return None
    monkeypatch.setattr(catalog.asyncio, "sleep", nosleep)
    return SimpleNamespace(pages=pages, rendered=rendered, fetched=fetched)


def add_page(pst, fake, url=BASE):
    fake[url] = UNSUP
    catalog.add_sources(pst.db, [url])
    return scan(pst, url)


# ------------------------------------------------------------ seznam z HTML
def test_unsupported_site_is_listed_from_html_with_paging(pst, fake, web):
    web.pages[BASE] = page_html(["a", "b"], pager=(0, 1, 2))
    web.pages[f"{BASE}?pg=1"] = page_html(["c", "d"], pager=(0, 1, 2))
    web.pages[f"{BASE}?pg=2"] = page_html(["d", "e"], pager=(0, 1, 2))          # d už je, e je nové
    web.pages[f"{BASE}?pg=3"] = page_html(["e"], pager=(0, 1, 2))                # nic nového: konec
    res = add_page(pst, fake)
    src = pst.db.query("select * from catalog_sources")[0]
    assert (src["kind"], src["status"], src["title"]) == ("page", "done", "Pořad Test") and src["folder"] == "Pořad Test"
    its = pst.db.query("select key, url, title, detail_state, state from catalog_items order by pos")
    assert [i["url"] for i in its] == [f"https://web.example/dily/{n}" for n in "abcde"]
    assert its[0]["key"] == its[0]["url"] and "Díl a" in its[0]["title"] and {i["detail_state"] for i in its} == {"pending"}
    assert res["total"] == 5 and not web.rendered                                # prohlížeč se nepoužil


def test_page_listing_failure_midway_is_incomplete_and_keeps_missing_videos(pst, fake, web):
    web.pages[BASE] = page_html(["a", "b"], pager=(0, 1))
    web.pages[f"{BASE}?pg=1"] = page_html(["c"], pager=(0, 1))
    web.pages[f"{BASE}?pg=2"] = page_html(["d"], pager=(0, 1))
    add_page(pst, fake)
    web.pages[f"{BASE}?pg=1"] = pagelist.PageError("HTTP 500")
    add_page_again = lambda: scan(pst, BASE)  # noqa: E731
    with pst.db.conn() as c:
        c.execute("update catalog_sources set status='queued'")
    add_page_again()
    assert {r["state"] for r in pst.db.query("select state from catalog_items")} == {"new"}          # nic se nepovažuje za zmizelé


def test_missing_next_page_is_the_end_of_the_list(pst, fake, web):
    web.pages[BASE] = page_html(["a", "b"], pager=(0, 1))
    web.pages[f"{BASE}?pg=1"] = pagelist.PageError("stránka vrací chybu HTTP 404")
    assert add_page(pst, fake)["total"] == 2
    web.pages[f"{BASE}?pg=1"] = page_html(["c", "d"], pager=(0, 1))
    web.pages[f"{BASE}?pg=2"] = pagelist.PageError("stránka vrací chybu HTTP 404")
    with pst.db.conn() as c:
        c.execute("update catalog_sources set status='queued'")
    scan(pst, BASE)
    assert pst.db.query("select count(*) n from catalog_items where state='new'")[0]["n"] == 4


def test_non_unsupported_errors_are_not_treated_as_pages(pst, fake, web):
    fake[BASE] = ResolveError("HTTP Error 429", "network")
    catalog.add_sources(pst.db, [BASE])
    scan(pst, BASE)
    src = pst.db.query("select * from catalog_sources")[0]
    assert src["status"] == "error" and "429" in src["error"] and not web.fetched


def test_page_without_list_uses_browser_when_enabled(pst, fake, web):
    web.pages[BASE] = "<html><body><p>Seznam se načítá skriptem</p></body></html>"
    web.rendered[BASE] = page_html(["x", "y"])
    add_page(pst, fake)
    assert pst.db.query("select count(*) n from catalog_items")[0]["n"] == 2 and web.rendered["calls"] == [BASE]


def test_page_without_list_fails_when_browser_disabled_or_list_missing(data, fake, web):
    s = PSt(data, catalog_slow_browser=False)
    web.pages[BASE] = "<html><body>nic</body></html>"
    add_page(s, fake)
    err = s.db.query("select status, error from catalog_sources")[0]
    assert err["status"] == "error" and "prohlížeč" in err["error"] and not web.rendered
    s2 = PSt(data, catalog_slow_browser=True)
    web.rendered[BASE] = "<html><body>pořád nic</body></html>"
    with s2.db.conn() as c:
        c.execute("update catalog_sources set status='queued'")
    scan(s2, BASE)
    err = s2.db.query("select status, error from catalog_sources")[0]
    assert err["status"] == "error" and "nenašel" in err["error"] and web.rendered["calls"] == [BASE]


def test_fetch_error_is_reported_on_the_source(pst, fake, web):
    web.pages[BASE] = pagelist.PageError("stránka vrací chybu HTTP 403")
    add_page(pst, fake)
    err = pst.db.query("select status, error from catalog_sources")[0]
    assert err["status"] == "error" and "403" in err["error"]


# ------------------------------------------------------------ pomalé podrobnosti
def make_page_items(st, fake, n=2, **kw):
    fake[BASE] = UNSUP
    catalog.add_sources(st.db, [BASE])
    with st.db.conn() as c:
        c.execute("update catalog_sources set status='done', title='Pořad', folder='Pořad', kind='page' where url=?", (BASE,))
        sid = c.execute("select id from catalog_sources").fetchone()[0]
        for i in range(n):
            c.execute("insert into catalog_items(source_id,key,url,host,title,search,pos,added_at,updated_at) values (?,?,?,?,?,?,?,?,?)",
                      (sid, f"https://web.example/dily/{i}", f"https://web.example/dily/{i}", "web.example", f"Díl {i}", f"dil {i}", i, 1, 1))


@pytest.fixture
def sniff(monkeypatch, info):
    calls, answers = [], {}

    async def fake_sniff(url, ctx):
        calls.append((url, len(info.calls)))
        a = answers.get(url, {"title": "Stránka", "thumbnail": "https://img.example/max.jpg", "drm": False, "candidates": [
            {"kind": "hls", "url": "https://cdn/x.m3u8", "height": 720, "rank": 0}]})
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(cd.sniffer, "sniff", fake_sniff)
    return SimpleNamespace(calls=calls, answers=answers)


def urls_of(calls):
    return [u for u, _ in calls]


def test_unsupported_item_waits_for_the_browser_and_is_checked_last(st_, fake, info, sniff):
    make_page_items(st_, fake, 2)
    info.answers["https://web.example/dily/0"] = ResolveError("Unsupported URL", "unsupported")
    info.answers["https://web.example/dily/1"] = ResolveError("Unsupported URL", "unsupported")
    with st_.db.conn() as c:                                                    # jiný web s funkčním yt-dlp, přidaný jako druhý
        c.execute("insert into catalog_items(source_id,key,url,host,title,search,pos,added_at,updated_at) values (1,'k','https://ok.example/v','ok.example','OK','ok',9,1,1)")
    asyncio.run(run_until(st_, lambda: all(v[0] in ("done",) for v in states(st_).values()), timeout=10))
    assert all(n == 3 for _, n in sniff.calls)                                  # prohlížeč začal, až když yt-dlp prošel všechna 3 videa
    r = rows(st_)["https://web.example/dily/0"]
    assert (r["height"], r["detail_state"], r["thumb_url"]) == (720, "done", "https://img.example/max.jpg") and r["title"] == "Díl 0"
    assert urls_of(sniff.calls) == ["https://web.example/dily/0", "https://web.example/dily/1"]      # po jednom


def test_slow_layer_is_off_when_disabled(data, fake, info, sniff):
    s = PSt(data, catalog_slow_browser=False)
    make_page_items(s, fake, 1)
    info.answers["https://web.example/dily/0"] = ResolveError("Unsupported URL", "unsupported")
    asyncio.run(run_until(s, lambda: states(s)["https://web.example/dily/0"][0] == "failed"))
    assert not sniff.calls and "unsupported" in rows(s)["https://web.example/dily/0"]["detail_error"]


def test_browser_without_video_or_with_drm_marks_the_item_failed(st_, fake, info, sniff):
    make_page_items(st_, fake, 2)
    for i in range(2):
        info.answers[f"https://web.example/dily/{i}"] = ResolveError("Unsupported URL", "unsupported")
    sniff.answers["https://web.example/dily/0"] = {"title": "", "thumbnail": None, "drm": False, "candidates": []}
    sniff.answers["https://web.example/dily/1"] = {"title": "", "thumbnail": None, "drm": True, "candidates": []}
    asyncio.run(run_until(st_, lambda: all(v[0] == "failed" for v in states(st_).values())))
    errs = [r["detail_error"] for r in st_.db.query("select detail_error from catalog_items order by pos")]
    assert "nepodařilo" in errs[0] and "DRM" in errs[1]


def test_browser_network_error_keeps_the_item_waiting_and_delays_the_site(st_, fake, info, sniff):
    make_page_items(st_, fake, 1)
    info.answers["https://web.example/dily/0"] = ResolveError("Unsupported URL", "unsupported")
    sniff.answers["https://web.example/dily/0"] = ResolveError("stránku nelze načíst: timeout", "network")
    w = asyncio.run(run_until(st_, lambda: bool(sniff.calls) and "web.example" in cd_backoff(st_)))
    assert states(st_)["https://web.example/dily/0"][0] == "slow" and "web.example" in w.backoff


def cd_backoff(st_):
    return ["web.example"] if st_.db.query("select 1 from catalog_items where detail_state='slow'") and True else []


def test_status_counts_slow_items(st_, fake, info, sniff):
    make_page_items(st_, fake, 2)
    with st_.db.conn() as c:
        c.execute("update catalog_items set detail_state='slow'")
    assert cd.DetailWorker(st_).status()["slow"] == 2


# ------------------------------------------------------------ automatické hledání
def test_auto_refresh_queues_only_old_idle_sources_as_automatic(pst):
    catalog.add_sources(pst.db, ["https://a.example/1", "https://a.example/2", "https://a.example/3", "https://a.example/4"])
    now = time.time()
    with pst.db.conn() as c:
        c.execute("update catalog_sources set status='done', last_scan=?, manual=1, scan_mode='all' where url like '%/1'", (now - 25 * 3600,))
        c.execute("update catalog_sources set status='done', last_scan=? where url like '%/2'", (now - 3600,))
        c.execute("update catalog_sources set status='error', last_scan=? where url like '%/3'", (now - 48 * 3600,))
        c.execute("update catalog_sources set status='scanning', last_scan=? where url like '%/4'", (now - 99 * 3600,))
    assert catalog.auto_refresh(pst.db, 24, now) == 2
    got = {r["url"][-1]: (r["status"], r["scan_mode"], r["manual"]) for r in pst.db.query("select * from catalog_sources")}
    assert got["1"] == ("queued", "all", 0)                                             # nevyřízené „načíst znovu vše“ se nezmění na „jen nová“
    assert got["3"] == ("queued", "new", 0)                                             # automatické, jen nová videa
    assert got["2"][0] == "done" and got["4"][0] == "scanning"                          # čerstvý a právě zjišťovaný zdroj se nechá
    assert catalog.auto_refresh(pst.db, 24, now) == 0                       # podruhé nic (už jsou ve frontě)


def test_auto_refresh_settings_are_validated(data):
    s = Settings()
    s.update({"catalog_auto": True, "catalog_auto_hours": 72})
    assert s.get("catalog_auto") is True and s.get("catalog_auto_hours") == 72
    with pytest.raises(ValueError):
        s.update({"catalog_auto_hours": 5})
    from viddown.config import DEFAULTS
    assert DEFAULTS["catalog_auto"] is False and DEFAULTS["catalog_slow_browser"] is True


def test_task_auto_refreshes_only_inside_the_window_and_when_enabled(pst, fake, monkeypatch):
    fake["https://a.example/1"] = {"_type": "playlist", "title": "Z", "extractor_key": "Youtube", "entries": []}
    catalog.add_sources(pst.db, ["https://a.example/1"])
    with pst.db.conn() as c:
        c.execute("update catalog_sources set status='done', last_scan=1, manual=1")
    calls = []
    monkeypatch.setattr(catalog, "auto_refresh", lambda db, hours, now=None: calls.append(hours) or 0)

    async def go(settings):
        pst.settings.update(settings)
        stop = asyncio.Event()
        t = asyncio.create_task(catalog.task(SimpleNamespace(db=pst.db, settings=pst.settings, data=pst.data, runner=pst.runner), stop))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(t, 5)
    asyncio.run(go({"catalog_auto": False}))
    assert calls == []
    asyncio.run(go({"catalog_auto": True, "catalog_auto_hours": 6}))
    assert calls and set(calls) == {6.0}


def test_auto_refresh_does_not_retry_unsupported_sites(pst):
    catalog.add_sources(pst.db, ["https://a.example/1", "https://a.example/2"])
    with pst.db.conn() as c:
        c.execute("update catalog_sources set status='error', last_scan=1, error='web není podporovaný a seznam videí se nenašel' where url like '%/1'")
        c.execute("update catalog_sources set status='error', last_scan=1, error='stránka vrací chybu HTTP 503' where url like '%/2'")
    assert catalog.auto_refresh(pst.db, 24) == 1
    assert pst.db.query("select status from catalog_sources where url like '%/2'")[0]["status"] == "queued"


# ------------------------------------------------------------ úplnost seznamu stránky (nález review)
def test_page_without_paging_is_incomplete_so_older_videos_are_not_marked_gone(pst, fake, web):
    web.pages[BASE] = page_html(["a", "b", "c"])
    add_page(pst, fake)
    web.pages[BASE] = page_html(["b", "c", "d"])                                       # „a“ vypadl z posledních dílů
    with pst.db.conn() as c:
        c.execute("update catalog_sources set status='queued'")
    scan(pst, BASE)
    assert {r["key"][-1]: r["state"] for r in pst.db.query("select key, state from catalog_items")} == {"a": "new", "b": "new", "c": "new", "d": "new"}


def test_empty_next_page_is_incomplete_but_seen_only_page_is_the_end(pst, fake, web):
    web.pages[BASE] = page_html(["a", "b"], pager=(0, 1))
    web.pages[f"{BASE}?pg=1"] = "<html><body>Potvrďte, že nejste robot</body></html>"      # měkká chyba: žádný díl
    add_page(pst, fake)
    web.pages[BASE] = page_html(["a", "b"], pager=(0, 1))
    web.pages[f"{BASE}?pg=1"] = page_html(["c", "d"], pager=(0, 1, 2))
    web.pages[f"{BASE}?pg=2"] = page_html(["c", "d"], pager=(0, 1, 2))                  # jen už známé: přirozený konec
    with pst.db.conn() as c:
        c.execute("update catalog_sources set status='queued'")
    scan(pst, BASE)
    assert pst.db.query("select count(*) n from catalog_items where state='new'")[0]["n"] == 4


def test_page_fetch_error_is_a_network_error_not_an_unsupported_site(pst, fake, web):
    web.pages[BASE] = pagelist.PageError("stránka vrací chybu HTTP 503")
    add_page(pst, fake)
    err = pst.db.query("select error from catalog_sources")[0]["error"]
    assert "503" in err and "není podporovaný" not in err


# ------------------------------------------------------------ pomalá vrstva (nálezy review)
def test_slow_pick_skips_backed_off_hosts_and_browser_off_drops_slow_items(st_, fake, info, sniff):
    make_page_items(st_, fake, 2)
    with st_.db.conn() as c:
        c.execute("update catalog_items set detail_state='slow'")
        c.execute("update catalog_items set host='other.example' where pos=1")
    w = cd.DetailWorker(st_)
    assert w.pick_slow(set())["pos"] == 0
    assert w.pick_slow({"web.example"})["host"] == "other.example"                       # odložený web neblokuje ostatní
    assert w.pick_slow({"web.example", "other.example"}) is None
    assert w.drop_slow() == 2
    assert {r["detail_state"] for r in st_.db.query("select detail_state from catalog_items")} == {"failed"}
    assert cd.retry_failed(st_.db)["details"] == 2                                       # po zapnutí prohlížeče jde vrátit do fronty


def test_missing_browser_engine_fails_the_item_instead_of_looping(st_, fake, info, sniff):
    make_page_items(st_, fake, 1)
    info.answers["https://web.example/dily/0"] = ResolveError("Unsupported URL", "unsupported")
    sniff.answers["https://web.example/dily/0"] = ResolveError("Chromium nelze spustit", "engine")
    asyncio.run(run_until(st_, lambda: states(st_)["https://web.example/dily/0"][0] == "failed"))


def test_browser_renders_all_pages_with_one_launch(pst, fake, web):
    web.pages[BASE] = "<html><body>skript</body></html>"
    web.rendered[BASE] = page_html(["a", "b"], pager=(0, 1))
    web.rendered[f"{BASE}?pg=1"] = page_html(["c", "d"], pager=(0, 1, 2))
    web.rendered[f"{BASE}?pg=2"] = page_html(["c", "d"], pager=(0, 1, 2))
    assert add_page(pst, fake)["total"] == 4
    assert web.rendered["launches"] == 1 and web.rendered["closed"] == 1 and len(web.rendered["calls"]) == 3


def test_retry_keeps_the_catalog_link_and_requeues_the_item(rt):
    from viddown import catalog as cat
    with rt.db.conn() as c:
        c.execute("insert into catalog_sources(id,url,status,added_at,folder) values (1,'https://s.example/p','done',1,'Složka')")
        c.execute("insert into catalog_items(id,source_id,key,url,state,detail_state,added_at,updated_at) values (5,1,'k','https://s.example/v','new','done',1,1)")
    jid, _ = rt.add("https://s.example/v", source="catalog", auto_confirm=True, catalog_item_id=5, subdir="Složka")
    rt.db.update(jid, status="failed", error="boom")
    cat.reconcile(rt.db)
    assert rt.db.query("select state from catalog_items")[0]["state"] == "new"
    new_id = rt.retry(jid)
    row = rt.db.query("select state, job_id from catalog_items")[0]
    assert (row["state"], row["job_id"]) == ("queued", new_id)
    j = rt.db.get(new_id)
    assert j["catalog_item_id"] == 5 and j["subdir"] == "Složka"


def test_fetch_limits_memory_and_rejects_non_html(monkeypatch):
    import httpx
    big = b"<html>" + b"x" * 5_000_000
    handlers = {"/big": httpx.Response(200, content=big, headers={"content-type": "text/html; charset=utf-8"}),
                "/video": httpx.Response(200, content=b"\0" * 100, headers={"content-type": "video/mp4"}),
                "/missing": httpx.Response(404, content=b"")}
    real = httpx.AsyncClient

    def client(*a, **kw):
        return real(*a, transport=httpx.MockTransport(lambda req: handlers[req.url.path]), **kw)
    monkeypatch.setattr(pagelist.httpx, "AsyncClient", client)
    text, final = asyncio.run(pagelist.fetch("https://w.example/big"))
    assert len(text) <= pagelist.MAX_BYTES and final == "https://w.example/big"
    for path, msg in (("/video", "nevede na webovou stránku"), ("/missing", "HTTP 404")):
        with pytest.raises(pagelist.PageError, match=msg):
            asyncio.run(pagelist.fetch("https://w.example" + path))
