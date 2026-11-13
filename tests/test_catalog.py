"""Katalog, etapa 1: přidání zdrojů, fronta zjišťování, uložení seznamu, „staženo dříve“, dotazy a API."""
import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_subscriptions import State, rt  # noqa: F401
from viddown import catalog
from viddown.config import Settings
from viddown.db import DB
from viddown.resolvers import ResolveError
from viddown.server import create_app


def e(vid, title=None, channel="Kanál", duration=60, ie="Youtube", **kw):
    return {"id": vid, "ie_key": ie, "url": f"https://example.com/watch/{vid}", "title": title or f"Video {vid}",
            "channel": channel, "duration": duration, **kw}


def playlist(entries, title="Seznam", **kw):
    return {"_type": "playlist", "title": title, "extractor_key": "Youtube", "entries": entries, **kw}


@pytest.fixture
def fake(monkeypatch):
    """Podvržené yt-dlp: slovník adresa -> odpověď (nebo výjimka)."""
    calls = []
    answers = {}

    async def probe(url, ctx, timeout=300, playlist_end=None):
        calls.append(url)
        a = answers[url]
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(catalog.ytdlp, "probe", probe)
    answers["calls"] = calls
    return answers


class St:
    def __init__(self, data):
        self.data = data
        self.settings = Settings()
        self.db = DB(data / "viddown.db")
        self.runner = SimpleNamespace(ctx=lambda: SimpleNamespace(settings={"channel_tabs": ["videos"]}))


@pytest.fixture
def st(data):
    return St(data)


def scan(st, url, mode="new"):
    src = st.db.query("select * from catalog_sources where url=?", (url,))[0]
    if src["scan_mode"] != mode:
        with st.db.conn() as c:
            c.execute("update catalog_sources set scan_mode=? where id=?", (mode, src["id"]))
        src["scan_mode"] = mode
    return asyncio.run(catalog.scan_one(st, src))


def add(st, *urls):
    return catalog.add_sources(st.db, list(urls))


# ------------------------------------------------------------ adresy
def test_parse_urls_comments_blank_invalid_and_duplicates():
    text = "\n# komentář\n  https://a.example/list  \nhttps://a.example/list\nneni-adresa\nftp://x.example/a\nhttps://b.example/c/ # poznámka\n\n"
    urls, invalid = catalog.parse_urls(text)
    assert urls == ["https://a.example/list", "https://b.example/c"]
    assert invalid == ["neni-adresa", "ftp://x.example/a"]
    assert catalog.parse_urls("") == ([], [])


def test_add_sources_reloads_existing_and_skips_scanning_and_reports_limit(st):
    r = add(st, "https://a.example/1", "https://a.example/2")
    assert len(r["added"]) == 2 and r["reloaded"] == [] and r["skipped"] == []
    with st.db.conn() as c:
        c.execute("update catalog_sources set status='done', scan_mode='new'")
    r = add(st, "https://a.example/2", "https://a.example/3")
    assert len(r["added"]) == 1 and len(r["reloaded"]) == 1 and r["skipped"] == []        # existující se načte znovu celá
    row = st.db.query("select status, scan_mode from catalog_sources where url='https://a.example/2'")[0]
    assert (row["status"], row["scan_mode"]) == ("queued", "all")
    with st.db.conn() as c:
        c.execute("update catalog_sources set status='scanning' where url='https://a.example/2'")
    r = add(st, "https://a.example/2")
    assert r["reloaded"] == [] and r["skipped"] == [{"url": "https://a.example/2", "reason": "právě se zjišťuje"}]
    many = [f"https://l.example/{i}" for i in range(catalog.MAX_URLS + 5)]
    r = add(st, *many)
    assert len(r["added"]) == catalog.MAX_URLS and len(r["skipped"]) == 5 and "limit" in r["skipped"][0]["reason"]


def test_norm_removes_diacritics_and_case():
    assert catalog.norm("  Žluťoučký  KŮŇ ") == "zlutoucky kun"
    assert catalog.norm(None) == ""


# ------------------------------------------------------------ zjištění seznamu
def test_scan_playlist_stores_items_and_source_meta(st, fake):
    fake["https://x.example/pl"] = playlist([e("a"), e("b", "Zahradní pergola", channel="Kanál B"), {"id": "x", "title": "bez adresy"}, None])
    add(st, "https://x.example/pl")
    res = scan(st, "https://x.example/pl")
    assert res == {"added": 2, "reoffered": 0, "restored": 0, "missing": 0, "total": 2}
    src = st.db.query("select * from catalog_sources")[0]
    assert src["status"] == "done" and src["kind"] == "playlist" and src["title"] == "Seznam" and src["folder"] == "Seznam"
    items = st.db.query("select * from catalog_items order by pos")
    assert [i["key"] for i in items] == ["youtube a", "youtube b"] and [i["pos"] for i in items] == [0, 1]
    assert items[1]["search"] == "zahradni pergola kanal b" and items[0]["detail_state"] == "pending" and items[0]["state"] == "new"


def test_scan_channel_reads_tabs_and_dedupes(st, fake, monkeypatch):
    st.runner = SimpleNamespace(ctx=lambda: SimpleNamespace(settings={"channel_tabs": ["videos", "shorts"]}))
    base = "https://www.youtube.com/@nejaky"
    fake[f"{base}/videos"] = playlist([e("a"), e("b")], title="Nejaky - Videos", channel="Nejaky")
    fake[f"{base}/shorts"] = playlist([e("b"), e("c")], title="Nejaky - Shorts")
    add(st, base)
    scan(st, base)
    src = st.db.query("select * from catalog_sources")[0]
    assert src["kind"] == "channel" and src["title"] == "Nejaky" and src["folder"] == "Nejaky"
    assert [i["key"] for i in st.db.query("select key from catalog_items order by pos")] == ["youtube a", "youtube b", "youtube c"]


def test_scan_single_video_has_details_and_no_folder(st, fake, monkeypatch):
    monkeypatch.setattr(catalog.ytdlp, "best_height", lambda i: 1080)
    monkeypatch.setattr(catalog.ytdlp, "size_estimate", lambda i: 123456)
    fake["https://v.example/one"] = {"id": "q1", "extractor_key": "Fiktivni", "title": "Jedno video", "webpage_url": "https://v.example/one",
                                     "duration": 90, "channel": "Autor", "thumbnail": "https://img/x.jpg"}
    add(st, "https://v.example/one")
    scan(st, "https://v.example/one")
    src = st.db.query("select * from catalog_sources")[0]
    it = st.db.query("select * from catalog_items")[0]
    assert src["kind"] == "video" and src["folder"] is None
    assert (it["key"], it["height"], it["size"], it["detail_state"], it["thumb_url"]) == ("fiktivni q1", 1080, 123456, "done", "https://img/x.jpg")


def test_scan_errors_are_stored_and_source_stays_for_retry(st, fake, monkeypatch):
    async def no_list(url, settings=None, timeout=30):
        return "<html><body>nic</body></html>", url
    monkeypatch.setattr(catalog.pagelist, "fetch", no_list)
    st.runner.ctx = lambda: SimpleNamespace(settings={"channel_tabs": ["videos"], "catalog_slow_browser": False})
    fake["https://a.example/1"] = ResolveError("ERROR: Unsupported URL: https://a.example/1", "unsupported")
    fake["https://a.example/2"] = playlist([])
    fake["https://a.example/3"] = RuntimeError("boom")
    add(st, "https://a.example/1", "https://a.example/2", "https://a.example/3")
    for i in (1, 2, 3):
        scan(st, f"https://a.example/{i}")
    rows = {r["url"][-1]: r for r in st.db.query("select * from catalog_sources")}
    assert all(r["status"] == "error" for r in rows.values())
    assert "není podporovaný" in rows["1"]["error"] and "prázdný" in rows["2"]["error"] and "boom" in rows["3"]["error"]
    assert st.db.query("select count(*) n from catalog_items")[0]["n"] == 0


def test_unavailable_videos_are_marked_gone(st, fake):
    fake["https://x.example/pl"] = playlist([e("a"), e("b", "[Private video]"), e("c", "[Deleted video]")])
    add(st, "https://x.example/pl")
    scan(st, "https://x.example/pl")
    assert {i["key"]: i["state"] for i in st.db.query("select key, state from catalog_items")} == \
        {"youtube a": "new", "youtube b": "gone", "youtube c": "gone"}
    assert catalog.query_items(st.db)["total"] == 1
    assert catalog.query_items(st.db, state=["gone"])["total"] == 2


# ------------------------------------------------------------ staženo dříve
def test_downloaded_before_from_archive_and_history(st, fake, data):
    (data / "archive.txt").write_text("youtube a\nyoutube OTHER\n", "utf-8")
    st.db.add("https://example.com/watch/b", status="done")
    st.db.add("https://example.com/watch/c", status="failed")
    fake["https://x.example/pl"] = playlist([e("a"), e("b"), e("c"), e("d")])
    add(st, "https://x.example/pl")
    scan(st, "https://x.example/pl")
    got = {i["key"]: i["downloaded_before"] for i in st.db.query("select key, downloaded_before from catalog_items")}
    assert got == {"youtube a": 1, "youtube b": 1, "youtube c": 0, "youtube d": 0}
    assert keys(catalog.query_items(st.db, state=["downloaded"])) == ["Video a", "Video b"]


# ------------------------------------------------------------ obnovení zdroje (varianta A)
def test_refresh_adds_only_never_offered_videos_and_reload_reoffers_with_flags(st, fake):
    url = "https://x.example/pl"
    fake[url] = playlist([e("a"), e("b"), e("c")])
    add(st, url)
    scan(st, url)
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    with st.db.conn() as c:                                   # a odstraněno, b staženo, c ve frontě
        c.execute("update catalog_items set state='removed' where key='youtube a'")
        c.execute("update catalog_items set state='done' where key='youtube b'")
        c.execute("update catalog_items set state='queued', job_id=5 where key='youtube c'")
    fake[url] = playlist([e("n"), e("a"), e("b"), e("c")])    # nové video je nahoře
    assert catalog.rescan_source(st.db, sid, "new") is True
    res = scan(st, url, "new")
    assert res == {"added": 1, "reoffered": 0, "restored": 0, "missing": 0, "total": 4}
    states = {i["key"]: i["state"] for i in st.db.query("select key, state from catalog_items")}
    assert states == {"youtube a": "removed", "youtube b": "done", "youtube c": "queued", "youtube n": "new"}
    assert [i["key"] for i in st.db.query("select key from catalog_items order by pos")] == ["youtube n", "youtube a", "youtube b", "youtube c"]

    assert catalog.rescan_source(st.db, sid, "all") is True
    res = scan(st, url, "all")
    assert res == {"added": 0, "reoffered": 2, "restored": 0, "missing": 0, "total": 4}
    rows = {i["key"]: i for i in st.db.query("select * from catalog_items")}
    assert rows["youtube a"]["state"] == "new" and rows["youtube a"]["rejected_before"] == 1 and rows["youtube a"]["downloaded_before"] == 0
    assert rows["youtube b"]["state"] == "new" and rows["youtube b"]["downloaded_before"] == 1 and rows["youtube b"]["rejected_before"] == 0
    assert rows["youtube c"]["state"] == "queued" and rows["youtube c"]["job_id"] == 5          # ve frontě se nesahá
    assert keys(catalog.query_items(st.db, state=["rejected"])) == ["Video a"]
    assert st.db.query("select scan_mode from catalog_sources")[0]["scan_mode"] == "new"


def test_rescan_states(st):
    add(st, "https://a.example/1")
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    assert catalog.rescan_source(st.db, 999, "new") is None
    with st.db.conn() as c:
        c.execute("update catalog_sources set status='scanning'")
    assert catalog.rescan_source(st.db, sid, "new") is False
    with pytest.raises(ValueError):
        catalog.rescan_source(st.db, sid, "jinak")


def test_delete_source_removes_items_and_memory(st, fake):
    url = "https://x.example/pl"
    fake[url] = playlist([e("a"), e("b")])
    add(st, url)
    scan(st, url)
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    with st.db.conn() as c:
        c.execute("update catalog_items set state='removed' where key='youtube a'")
    assert catalog.delete_source(st.db, sid) is True and catalog.delete_source(st.db, sid) is False
    assert st.db.query("select count(*) n from catalog_items")[0]["n"] == 0
    add(st, url)                                              # opětovné přidání: vše znovu, bez odznaku odmítnutí
    scan(st, url)
    assert {i["rejected_before"] for i in st.db.query("select rejected_before from catalog_items")} == {0}


def test_source_deleted_while_scanning_is_not_resurrected(st, fake, monkeypatch):
    url = "https://x.example/pl"
    fake[url] = playlist([e("a")])
    add(st, url)
    src = st.db.query("select * from catalog_sources")[0]
    orig = catalog.list_source

    async def slow(u, ctx):
        r = await orig(u, ctx)
        catalog.delete_source(st.db, src["id"])               # uživatel zdroj smazal během zjišťování
        return r
    monkeypatch.setattr(catalog, "list_source", slow)
    assert asyncio.run(catalog.scan_one(st, src)) == {}
    assert st.db.query("select count(*) n from catalog_items")[0]["n"] == 0
    assert st.db.query("select count(*) n from catalog_sources")[0]["n"] == 0


# ------------------------------------------------------------ dotazy
@pytest.fixture
def filled(st, fake):
    fake["https://x.example/a"] = playlist([e("a1", "Zahradní pergola", channel="Řemeslo"), e("a2", "Opravy kol", channel="Řemeslo"),
                                            e("a3", "Dokument o tunelu", channel="Stavby")], title="Zdroj Alfa")
    fake["https://x.example/b"] = playlist([e("b1", "Test kombíku", channel="Auta"), e("b2", "Pergola ze dřeva", channel="Auta")], title="Béčko")
    add(st, "https://x.example/a", "https://x.example/b")
    scan(st, "https://x.example/a")
    scan(st, "https://x.example/b")
    h = {"youtube a1": (1080, 400, 600.0), "youtube a2": (480, 90, 300.0), "youtube a3": (2160, 6800, 3600.0), "youtube b1": (720, None, None),
         "youtube b2": (None, 250, 120.0)}
    with st.db.conn() as c:
        for k, (height, size, dur) in h.items():
            c.execute("update catalog_items set height=?, size=?, duration=? where key=?", (height, size, dur, k))
    return st


def keys(r):
    return [i["title"] for i in r["items"]]


def test_query_text_search_is_accent_insensitive_and_covers_source_and_channel(filled):
    db = filled.db
    assert keys(catalog.query_items(db, q="pergola")) == ["Pergola ze dřeva", "Zahradní pergola"]    # výchozí řazení: zdroj („Béčko“ před „Zdroj Alfa“), pořadí
    assert keys(catalog.query_items(db, q="ZAHRADNI pergola")) == ["Zahradní pergola"]        # všechna slova
    assert keys(catalog.query_items(db, q="remeslo")) == ["Zahradní pergola", "Opravy kol"]    # název kanálu
    assert keys(catalog.query_items(db, q="becko")) == ["Test kombíku", "Pergola ze dřeva"]    # název zdroje
    assert catalog.query_items(db, q="100%_")["total"] == 0                                     # zástupné znaky se neinterpretují
    assert catalog.query_items(db, q="")["total"] == 5


def test_query_resolution_buckets(filled):
    db = filled.db
    assert keys(catalog.query_items(db, res=["480"])) == ["Opravy kol"]
    assert keys(catalog.query_items(db, res=["2160", "720"], sort="height")) == ["Test kombíku", "Dokument o tunelu"]
    assert keys(catalog.query_items(db, res=["unknown"])) == ["Pergola ze dřeva"]
    assert keys(catalog.query_items(db, res=["360"])) == []
    assert catalog.query_items(db, res=["nesmysl"])["total"] == 5            # neznámý příznak se ignoruje


def test_query_sorting_keeps_unknown_values_last(filled):
    db = filled.db
    assert keys(catalog.query_items(db, sort="height", direction="desc")) == ["Dokument o tunelu", "Zahradní pergola", "Test kombíku", "Opravy kol", "Pergola ze dřeva"]
    assert keys(catalog.query_items(db, sort="height", direction="asc"))[-1] == "Pergola ze dřeva"
    assert keys(catalog.query_items(db, sort="size", direction="desc")) == ["Dokument o tunelu", "Zahradní pergola", "Pergola ze dřeva", "Opravy kol", "Test kombíku"]
    assert keys(catalog.query_items(db, sort="duration"))[:2] == ["Pergola ze dřeva", "Opravy kol"]
    assert keys(catalog.query_items(db, sort="source"))[:3] == ["Test kombíku", "Pergola ze dřeva", "Zahradní pergola"]   # „becko“ před „zdroj alfa“
    assert keys(catalog.query_items(db, sort="source", direction="desc"))[:2] == ["Zahradní pergola", "Opravy kol"]
    assert keys(catalog.query_items(db, sort="nesmysl"))[:1] == ["Test kombíku"]                                         # výchozí: zdroj, pořadí


def test_query_paging_and_source_filter(filled):
    db = filled.db
    r = catalog.query_items(db, limit=2, offset=0, sort="height", direction="desc")
    assert r["total"] == 5 and len(r["items"]) == 2
    r2 = catalog.query_items(db, limit=2, offset=2, sort="height", direction="desc")
    assert {i["id"] for i in r["items"]}.isdisjoint({i["id"] for i in r2["items"]})
    sid = db.query("select id from catalog_sources where title='Béčko'")[0]["id"]
    assert catalog.query_items(db, source=sid)["total"] == 2
    assert len(catalog.query_items(db, limit=10 ** 6)["items"]) == 5          # strop na velikost stránky


def test_query_state_filters_and_overview(filled):
    db = filled.db
    with db.conn() as c:
        c.execute("update catalog_items set state='queued' where key='youtube a1'")
        c.execute("update catalog_items set state='removed' where key='youtube a2'")
    assert catalog.query_items(db)["total"] == 4                              # odstraněné se nezobrazuje
    assert keys(catalog.query_items(db, state=["queued"])) == ["Zahradní pergola"]
    ov = catalog.sources_out(db)
    alfa = next(s for s in ov["sources"] if s["title"] == "Zdroj Alfa")
    assert alfa["items"] == 2 and alfa["queued"] == 1 and ov["items"] == 4 and ov["scanning"] == 0


# ------------------------------------------------------------ fronta zjišťování
def test_task_processes_queue_and_resumes_after_restart(st, fake):
    fake["https://x.example/1"] = playlist([e("a")], title="Jedna")
    fake["https://x.example/2"] = playlist([e("b")], title="Dva")
    add(st, "https://x.example/1", "https://x.example/2")
    with st.db.conn() as c:                                   # první zdroj zůstal „zjišťuje se“ po restartu
        c.execute("update catalog_sources set status='scanning' where url='https://x.example/1'")

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(catalog.task(st, stop))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if st.db.query("select count(*) n from catalog_sources where status='done'")[0]["n"] == 2:
                break
        stop.set()
        await asyncio.wait_for(t, 5)
    asyncio.run(go())
    assert [s["status"] for s in st.db.query("select status from catalog_sources order by id")] == ["done", "done"]
    assert fake["calls"] == ["https://x.example/1", "https://x.example/2"]                    # postupně, ve pořadí přidání


# ------------------------------------------------------------ migrace
def test_migration_creates_catalog_tables_and_jobs_column(tmp_path):
    from viddown import db as dbm
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    for ver, step in dbm.MIGRATIONS[:7]:
        if isinstance(step, str):
            for sql in dbm._split_sql(step):
                c.execute(sql)
        else:
            step(c)
    c.execute("pragma user_version=7")
    c.commit()
    c.close()
    d = DB(p)
    assert d.schema_version == dbm.MIGRATIONS[-1][0] >= 8
    names = {r["name"] for r in d.query("select name from sqlite_master where type='table'")}
    assert {"catalog_sources", "catalog_items"} <= names
    assert "catalog_item_id" in {r["name"] for r in d.query("pragma table_info(jobs)")}
    assert (tmp_path / "old.db.v7.bak").exists()


# ------------------------------------------------------------ API
@pytest.fixture
def client(rt, data, monkeypatch):
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    s = State(rt, data)
    s.db = DB(data / "t.db")
    return TestClient(create_app(s)), s


def test_api_add_list_refresh_reload_delete(client):
    c, s = client
    r = c.post("/api/catalog/sources", json={"text": "# zdroje\nhttps://a.example/1\nhttps://a.example/2\nspatne\n", "urls": ["https://a.example/3", "https://a.example/1"]})
    assert r.status_code == 200
    j = r.json()
    assert len(j["added"]) == 3 and j["invalid"] == ["spatne"] and j["overview"]["scanning"] == 3
    again = c.post("/api/catalog/sources", json={"text": "HTTPS://A.example/1/"}).json()      # stejná adresa po normalizaci
    assert again["added"] == [] and len(again["reloaded"]) == 1 and again["skipped"] == []
    assert c.post("/api/catalog/sources", json={"text": "  \n# nic"}).status_code == 400
    ov = c.get("/api/catalog").json()
    sid = ov["sources"][0]["id"]
    with s.db.conn() as cc:
        cc.execute("update catalog_sources set status='done'")
    assert c.post(f"/api/catalog/sources/{sid}/refresh").json()["scanning"] == 1
    assert c.post(f"/api/catalog/sources/{sid}/refresh").status_code == 200            # už ve frontě: znovu zařadí
    with s.db.conn() as cc:
        cc.execute("update catalog_sources set status='scanning' where id=?", (sid,))
    assert c.post(f"/api/catalog/sources/{sid}/reload").status_code == 409
    assert c.post("/api/catalog/sources/9999/refresh").status_code == 404
    assert c.delete(f"/api/catalog/sources/{sid}").json()["sources"].__len__() == 2
    assert c.delete(f"/api/catalog/sources/{sid}").status_code == 404


def test_api_items_filters_sorting_and_paging(client, fake):
    c, s = client
    fake["https://x.example/a"] = playlist([e("a1", "Zahradní pergola"), e("a2", "Opravy kol"), e("a3", "Tunel")], title="Alfa")
    catalog.add_sources(s.db, ["https://x.example/a"])
    st = St(s.data)
    st.db = s.db
    scan(st, "https://x.example/a")
    with s.db.conn() as cc:
        cc.execute("update catalog_items set height=case key when 'youtube a1' then 1080 when 'youtube a2' then 480 else 2160 end")
    j = c.get("/api/catalog/items", params={"q": "pergola"}).json()
    assert j["total"] == 1 and j["items"][0]["title"] == "Zahradní pergola" and j["items"][0]["source_title"] == "Alfa"
    j = c.get("/api/catalog/items", params={"res": "480,2160", "sort": "height", "dir": "desc"}).json()
    assert [i["height"] for i in j["items"]] == [2160, 480]
    j = c.get("/api/catalog/items", params={"limit": 1, "offset": 1, "sort": "height", "dir": "asc"}).json()
    assert j["total"] == 3 and len(j["items"]) == 1 and j["items"][0]["height"] == 1080
    it = c.get("/api/catalog/items").json()["items"][0]
    assert set(it) >= {"id", "title", "url", "duration", "height", "size", "state", "downloaded_before", "rejected_before", "has_thumb", "source_folder"}


# ------------------------------------------------------------ doplněno podle review
def test_parse_urls_normalization_edge_cases():
    parse = lambda t: catalog.parse_urls(t)[0]  # noqa: E731
    assert parse("https://example.com//") == ["https://example.com"]                     # lomítka se neořezávají z „//“ ve schématu
    assert parse("https://example.com/a/;p=1") == ["https://example.com/a/;p=1"]          # parametry se nemění
    assert parse("https://example.com/c/?x=1\nhttps://example.com/c?x=1") == ["https://example.com/c?x=1"]
    assert parse("https://example.com/c/#f") == ["https://example.com/c#f"]
    assert parse("HTTPS://EXAMPLE.com/Cesta\nhttps://example.com/Cesta") == ["https://example.com/Cesta"]   # hostitel malými, cesta beze změny
    assert parse("https://Uzivatel:Heslo@Host.example/x/") == ["https://Uzivatel:Heslo@host.example/x"]
    assert parse("https://example.com/") == ["https://example.com/"]
    urls, invalid = catalog.parse_urls("https://\nhttp://[::1\nhttps:///x\nmailto:a@b.c")
    assert urls == [] and len(invalid) == 4


def test_reload_refreshes_metadata_and_handles_unavailable_and_restored(st, fake):
    url = "https://x.example/pl"
    fake[url] = playlist([e("a", "Starý název", channel="Autor 1"), e("b", "[Private video]")])
    add(st, url)
    scan(st, url)
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    assert {i["key"]: i["state"] for i in st.db.query("select key, state from catalog_items")} == {"youtube a": "new", "youtube b": "gone"}
    fake[url] = playlist([e("a", "Nový název", channel="Autor 2", duration=99), e("b", "Zveřejněno znovu")])
    catalog.rescan_source(st.db, sid, "all")
    res = scan(st, url, "all")
    assert res["restored"] == 1 and res["reoffered"] == 0                                   # gone → new, ale bez odznaků
    rows = {i["key"]: i for i in st.db.query("select * from catalog_items")}
    assert rows["youtube b"]["state"] == "new" and rows["youtube b"]["title"] == "Zveřejněno znovu"
    assert rows["youtube b"]["rejected_before"] == 0 and rows["youtube b"]["downloaded_before"] == 0
    assert (rows["youtube a"]["title"], rows["youtube a"]["channel"], rows["youtube a"]["duration"]) == ("Nový název", "Autor 2", 99)
    assert catalog.query_items(st.db, q="novy nazev autor 2")["total"] == 1                # vyhledávací text se přepočítal
    # zase soukromé: viditelná se skryje, odstraněná zůstane odstraněná a nevrací se jako odmítnutá
    with st.db.conn() as c:
        c.execute("update catalog_items set state='removed' where key='youtube a'")
    fake[url] = playlist([e("a", "[Deleted video]"), e("b", "[Private video]")])
    res = scan(st, url, "all")
    rows = {i["key"]: i for i in st.db.query("select * from catalog_items")}
    assert rows["youtube a"]["state"] == "removed" and rows["youtube b"]["state"] == "gone" and res["reoffered"] == 0
    assert rows["youtube b"]["title"] == "Zveřejněno znovu"                                # zástupný název nepřepíše skutečný


def test_missing_videos_are_hidden_only_when_listing_is_complete(st, fake):
    st.runner = SimpleNamespace(ctx=lambda: SimpleNamespace(settings={"channel_tabs": ["videos", "shorts"]}))
    base = "https://www.youtube.com/@nejaky"
    fake[f"{base}/videos"] = playlist([e("a"), e("b")], title="N - Videos", channel="N")
    fake[f"{base}/shorts"] = playlist([e("s1")], title="N - Shorts")
    add(st, base)
    scan(st, base)
    states = lambda: {i["key"]: i["state"] for i in st.db.query("select key, state from catalog_items")}  # noqa: E731
    assert states() == {"youtube a": "new", "youtube b": "new", "youtube s1": "new"}
    # záložka shorts selže: seznam je neúplný, nic se neskrývá
    fake[f"{base}/videos"] = playlist([e("a")], title="N - Videos", channel="N")
    fake[f"{base}/shorts"] = ResolveError("síť", "network")
    res = scan(st, base, "new")
    assert res["missing"] == 0 and set(states().values()) == {"new"}
    # úplný seznam: b zmizelo ze zdroje, s1 taky
    fake[f"{base}/shorts"] = playlist([], title="N - Shorts")
    res = scan(st, base, "new")
    assert res["missing"] == 2 and states() == {"youtube a": "new", "youtube b": "gone", "youtube s1": "gone"}
    # b se vrátilo
    fake[f"{base}/videos"] = playlist([e("b"), e("a")], title="N - Videos", channel="N")
    res = scan(st, base, "new")
    assert res["restored"] == 1 and states()["youtube b"] == "new"
    assert [i["key"] for i in st.db.query("select key from catalog_items where state='new' order by pos")] == ["youtube b", "youtube a"]


def test_queued_and_removed_items_survive_missing_from_listing(st, fake):
    url = "https://x.example/pl"
    fake[url] = playlist([e("a"), e("b"), e("c")])
    add(st, url)
    scan(st, url)
    with st.db.conn() as c:
        c.execute("update catalog_items set state='queued', job_id=3 where key='youtube a'")
        c.execute("update catalog_items set state='removed' where key='youtube b'")
    fake[url] = playlist([e("c")])
    scan(st, url, "new")
    assert {i["key"]: i["state"] for i in st.db.query("select key, state from catalog_items")} == \
        {"youtube a": "queued", "youtube b": "removed", "youtube c": "new"}


def test_keys_without_ie_key_use_url_and_ids_match_the_archive(st, fake, data):
    (data / "archive.txt").write_text("fiktivni 123\nyoutube AbC\n", "utf-8")
    nested = {"_type": "playlist", "extractor_key": "SiteUser", "entries": [{"_type": "url", "id": "123", "url": "https://s.example/v/123", "title": "Bez extraktoru"}]}
    fake["https://s.example/user"] = playlist([nested, e("AbC"), e("abc")])
    add(st, "https://s.example/user")
    scan(st, "https://s.example/user")
    rows = {i["key"]: i for i in st.db.query("select * from catalog_items")}
    assert set(rows) == {"https://s.example/v/123", "youtube AbC", "youtube abc"}          # extraktor se z playlistu nevymýšlí
    assert rows["https://s.example/v/123"]["downloaded_before"] == 1                       # shoda přes samotné id z archivu
    assert rows["youtube AbC"]["downloaded_before"] == 1 and rows["youtube abc"]["downloaded_before"] == 0   # velikost písmen id platí


def test_sources_with_the_same_title_do_not_interleave(st, fake):
    fake["https://x.example/1"] = playlist([e("x0"), e("x1"), e("x2")], title="Oblíbené")
    fake["https://x.example/2"] = playlist([e("y0"), e("y1"), e("y2")], title="Oblíbené")
    add(st, "https://x.example/1", "https://x.example/2")
    scan(st, "https://x.example/1")
    scan(st, "https://x.example/2")
    for sort in ("pos", "source", "height"):
        r = catalog.query_items(st.db, sort=sort)
        assert keys(r) == ["Video x0", "Video x1", "Video x2", "Video y0", "Video y1", "Video y2"], sort
    assert keys(catalog.query_items(st.db, sort="pos", direction="desc"))[:3] == ["Video x2", "Video x1", "Video x0"]


def test_claim_is_atomic_and_scan_mode_survives_a_request_made_during_scan(st):
    add(st, "https://a.example/1", "https://a.example/2")
    a = catalog.claim_source(st.db)
    b = catalog.claim_source(st.db)
    assert a["url"].endswith("/1") and b["url"].endswith("/2") and a["status"] == "scanning"
    assert catalog.claim_source(st.db) is None
    with st.db.conn() as c:                                   # během zjišťování přišla žádost „načíst vše“
        c.execute("update catalog_sources set scan_mode='all' where id=?", (a["id"],))
    res = catalog.apply_listing(st.db, a["id"], {"kind": "playlist", "title": "T", "entries": [{"key": "k", "id": None, "url": "https://a.example/v"}]},
                                "new", set(), set(), set())
    assert res["added"] == 1
    assert st.db.query("select scan_mode from catalog_sources where id=?", (a["id"],))[0]["scan_mode"] == "all"   # požadavek se neztratil


def test_task_stops_promptly_during_a_running_scan_and_requeues_the_source(st, monkeypatch):
    add(st, "https://a.example/1")
    started = asyncio.Event()

    async def slow(url, ctx):
        started.set()
        await asyncio.sleep(60)
    monkeypatch.setattr(catalog, "list_source", slow)

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(catalog.task(st, stop))
        await asyncio.wait_for(started.wait(), 5)
        t0 = asyncio.get_running_loop().time()
        stop.set()
        await asyncio.wait_for(t, 3)
        return asyncio.get_running_loop().time() - t0
    assert asyncio.run(go()) < 2
    assert st.db.query("select status from catalog_sources")[0]["status"] == "queued"      # po restartu se zjišťování naváže


def test_task_survives_a_database_error(st, fake, monkeypatch):
    fake["https://x.example/1"] = playlist([e("a")], title="Jedna")
    add(st, "https://x.example/1")
    real, calls = catalog.claim_source, []

    def flaky(db, manual_only=False):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(db, manual_only)

    async def fast(stop, sec):
        await asyncio.sleep(0.01)
    monkeypatch.setattr(catalog, "claim_source", flaky)
    monkeypatch.setattr(catalog, "_sleep", fast)

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(catalog.task(st, stop))
        for _ in range(200):
            await asyncio.sleep(0.02)
            if st.db.query("select status from catalog_sources")[0]["status"] == "done":
                break
        assert not t.done()                                   # smyčka přežila chybu
        stop.set()
        await asyncio.wait_for(t, 3)
    asyncio.run(go())
    assert st.db.query("select status from catalog_sources")[0]["status"] == "done" and len(calls) >= 2


def test_api_rejects_malformed_input_and_extreme_values(client):
    c, s = client
    assert c.post("/api/catalog/sources", json=[1, 2]).status_code == 400
    assert c.post("/api/catalog/sources", json={"urls": "https://a.example/x"}).status_code == 400
    assert c.post("/api/catalog/sources", json={"urls": [1, 2]}).status_code == 400
    assert c.post("/api/catalog/sources", content=b"neni json", headers={"Content-Type": "application/json"}).status_code == 400
    assert c.post("/api/catalog/sources", json={"text": "x" * 1_000_001}).status_code == 413
    r = c.post("/api/catalog/sources", json={"text": "\n".join(f"spatne {i}" for i in range(80))}).json()
    assert len(r["invalid"]) == 50 and r["invalid_count"] == 80
    assert c.get("/api/catalog/items", params={"offset": 10 ** 20, "limit": 10 ** 20}).status_code == 200
    assert c.get("/api/catalog/items", params={"source": 10 ** 30}).json()["total"] == 0
    assert c.get("/api/catalog/items", params={"q": " ".join(f"slovo{i}" for i in range(500))}).status_code == 200


def test_migration_keeps_existing_jobs_and_creates_indexes(tmp_path):
    from viddown import db as dbm
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    for ver, step in dbm.MIGRATIONS[:7]:
        if isinstance(step, str):
            for sql in dbm._split_sql(step):
                c.execute(sql)
        else:
            step(c)
    c.execute("insert into jobs(url, source, status, pos, created_at, updated_at) values('https://a.example/x','gui','done',1,1,1)")
    c.execute("pragma user_version=7")
    c.commit()
    c.close()
    d = DB(p)
    assert d.query("select url, catalog_item_id from jobs") == [{"url": "https://a.example/x", "catalog_item_id": None}]
    idx = {r["name"] for r in d.query("select name from sqlite_master where type='index'")}
    assert {"catalog_items_key", "catalog_items_state", "catalog_items_height", "catalog_items_size"} <= idx
