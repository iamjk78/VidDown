"""Katalog, animované náhledy, etapa 1: rozpoznání, uložení adresy, stahování s limitem, služba souboru, mazání, migrace 9."""
import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

from tests.test_catalog import client, e, fake, playlist, rt, scan  # noqa: F401
from tests.test_catalog_details import St as DSt, images, info, make, rows, run_until, states  # noqa: F401
from viddown import catalog, catalogdetails as cd
from viddown.config import DEFAULTS, Settings
from viddown.db import DB
from viddown import thumbs as _thumbs

REAL_THUMB_FETCH = _thumbs.fetch            # autouse fixture `images` podvrhuje thumbs.fetch; skutečnou funkci si uložíme předem

MP4 = b"\x00\x00\x00\x18ftypisom" + b"x" * 300
WEBM = b"\x1a\x45\xdf\xa3" + b"x" * 300
GIF = b"GIF89a" + b"x" * 300
WEBP_ANIM = b"RIFF\x00\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x12" + b"x" * 300      # příznak animace (bit 1) v bajtu 20
WEBP_STATIC = b"RIFF\x00\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x10" + b"x" * 300
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 300


@pytest.fixture
def st(data):
    s = DSt(data)
    s.settings.update({"catalog_anim": True})
    return s


@pytest.fixture
def web(monkeypatch):
    """Falešný web pro stahování animací: adresa -> (stav, tělo, hlavičky)."""
    pages, hits = {}, []
    real = httpx.Client

    def handler(req):
        hits.append(str(req.url))
        code, body, hdr = pages.get(str(req.url), (404, b"", {}))
        return httpx.Response(code, content=body, headers=hdr)

    def client(*a, **kw):
        return real(*a, transport=httpx.MockTransport(handler), **kw)
    monkeypatch.setattr(cd.httpx, "Client", client)
    return type("W", (), {"pages": pages, "hits": hits})


def anim_rows(st):
    return {r["key"]: r for r in st.db.query("select * from catalog_items")}


# ------------------------------------------------------------ rozpoznání v seznamu miniatur
@pytest.mark.parametrize("thumbs,expected", [
    ([{"url": "https://c/a.jpg"}], None),
    ([{"url": "https://c/a.jpg"}, {"url": "https://c/a.gif"}], "https://c/a.gif"),
    ([{"url": "https://c/a.gif"}, {"url": "https://c/a.mp4?x=1"}, {"url": "https://c/a.webp", "id": "animated"}], "https://c/a.mp4?x=1"),   # nejmenší formát
    ([{"url": "https://c/a.gif"}, {"url": "https://c/a_anim.webp"}], "https://c/a_anim.webp"),
    ([{"url": "https://c/a.webp"}, {"url": "https://c/b.webp", "id": "hq"}], None),                      # běžný statický WebP se nepočítá
    ([{"url": "https://c/a.webm"}], "https://c/a.webm"),
    ([{"url": "ftp://c/a.gif"}, {"url": ""}, {}], None),
])
def test_anim_candidate(thumbs, expected):
    assert catalog.anim_candidate({"thumbnails": thumbs}) == expected


def test_anim_candidate_uses_the_thumbnail_field_too():
    assert catalog.anim_candidate({"thumbnail": "https://c/x.gif"}) == "https://c/x.gif"
    assert catalog.anim_candidate({}) is None


def test_listing_stores_the_animation_url_even_when_the_setting_is_off(data, fake):
    from tests.test_catalog import St as LSt
    s = LSt(data)
    fake["https://x.example/pl"] = playlist([e("a", thumbnails=[{"url": "https://c/a.jpg"}, {"url": "https://c/a.mp4"}]), e("b")])
    catalog.add_sources(s.db, ["https://x.example/pl"])
    scan(s, "https://x.example/pl")
    got = {r["key"]: (r["anim_url"], r["anim_file"]) for r in s.db.query("select * from catalog_items")}
    assert got == {"youtube a": ("https://c/a.mp4", None), "youtube b": (None, None)}


def test_details_store_the_animation_url(st, fake, info):
    make(st, fake, [e("a")])
    info.answers["https://example.com/watch/a"] = {**info.default, "thumbnails": [{"url": "https://img/s.jpg"}, {"url": "https://img/a.gif"}]}
    asyncio.run(run_until(st, lambda: states(st)["youtube a"][0] == "done"))
    assert rows(st)["youtube a"]["anim_url"] == "https://img/a.gif"


# ------------------------------------------------------------ rozpoznání obsahu a stahování
@pytest.mark.parametrize("data_,kind", [(MP4, "mp4"), (WEBM, "webm"), (GIF, "gif"), (WEBP_ANIM, "webp"), (WEBP_STATIC, None), (JPEG, None), (b"<html>", None), (b"", None)])
def test_anim_kind(data_, kind):
    assert cd.anim_kind(data_[:64]) == kind


def test_download_anim_saves_validates_and_limits(tmp_path, web):
    f = tmp_path / "t"
    web.pages.update({"https://c/a.mp4": (200, MP4, {"content-type": "video/mp4"}), "https://c/s.webp": (200, WEBP_STATIC, {}),
                      "https://c/page": (200, b"<html>chyba</html>", {"content-type": "text/html"}), "https://c/big.gif": (200, GIF + b"y" * 5000, {}),
                      "https://c/gone.gif": (404, b"", {})})
    assert cd.download_anim(f, 7, "https://c/a.mp4", 10_000) == "7.anim.mp4" and (f / "7.anim.mp4").read_bytes() == MP4
    assert cd.download_anim(f, 7, "https://c/s.webp", 10_000) is None                    # statický obrázek není animace
    assert cd.download_anim(f, 7, "https://c/page", 10_000) is None
    assert cd.download_anim(f, 7, "https://c/gone.gif", 10_000) is None
    assert cd.download_anim(f, 7, "https://c/big.gif", 1000) is None                      # nad limit (hlavička nebo počítání)
    assert not list(f.glob("*.part")) and sorted(p.name for p in f.iterdir()) == ["7.anim.mp4"]
    web.pages["https://c/a2.gif"] = (200, GIF, {})
    assert cd.download_anim(f, 7, "https://c/a2.gif", 10_000) == "7.anim.gif"
    assert sorted(p.name for p in f.iterdir()) == ["7.anim.gif"]                          # po změně formátu jediný soubor


def test_download_anim_limit_without_content_length(tmp_path, monkeypatch):
    real = httpx.Client

    def chunked(*a, **kw):
        def handler(req):
            def gen():
                yield GIF
                for _ in range(20):
                    yield b"z" * 100
            return httpx.Response(200, content=gen())
        return real(*a, transport=httpx.MockTransport(handler), **kw)
    monkeypatch.setattr(cd.httpx, "Client", chunked)
    assert cd.download_anim(tmp_path / "t", 1, "https://c/x.gif", 1000) is None
    assert cd.download_anim(tmp_path / "t", 1, "https://c/x.gif", 100_000) == "1.anim.gif"


# ------------------------------------------------------------ smyčka na pozadí
def with_anims(st, fake, urls):
    make(st, fake, [e(k, thumbnail=f"https://img.example/{k}.jpg") for k in urls])
    with st.db.conn() as c:
        for k, u in urls.items():
            c.execute("update catalog_items set anim_url=?, detail_state='done' where key=?", (u, f"youtube {k}"))


def test_loop_downloads_animations_after_thumbnails_when_enabled(st, fake, info, web):
    with_anims(st, fake, {"a": "https://c/a.gif", "b": "https://c/b.mp4", "c": "https://c/c.gif", "d": None})
    web.pages.update({"https://c/a.gif": (200, GIF, {}), "https://c/b.mp4": (200, MP4, {}), "https://c/c.gif": (200, JPEG, {})})
    asyncio.run(run_until(st, lambda: all(r["anim_file"] is not None for r in anim_rows(st).values() if r["anim_url"]), thumbs=True))
    r = anim_rows(st)
    assert (r["youtube a"]["anim_file"], r["youtube b"]["anim_file"]) == (f"{r['youtube a']['id']}.anim.gif", f"{r['youtube b']['id']}.anim.mp4")
    assert r["youtube c"]["anim_file"] == "" and r["youtube d"]["anim_file"] is None     # nepodařilo se: prázdné; bez adresy: nic
    folder = catalog.thumbs_dir(st.data, st.settings)
    assert (folder / r["youtube a"]["anim_file"]).read_bytes() == GIF
    assert all(r[k]["thumb_file"] for k in r)                                             # statické miniatury zůstaly


def test_loop_ignores_animations_when_disabled_or_paused_or_outside_the_window(st, fake, info, web):
    st.settings.update({"catalog_anim": False})
    with_anims(st, fake, {"a": "https://c/a.gif"})
    web.pages["https://c/a.gif"] = (200, GIF, {})

    async def go():
        w = cd.DetailWorker(st)
        stop = asyncio.Event()
        t = asyncio.create_task(w.thumbs_loop(stop))
        await asyncio.sleep(0.8)
        stop.set()
        await asyncio.wait_for(t, 5)
    asyncio.run(go())
    assert anim_rows(st)["youtube a"]["anim_file"] is None and "https://c/a.gif" not in web.hits


def test_removed_item_does_not_keep_a_downloaded_animation(st, fake, info, web):
    with_anims(st, fake, {"a": "https://c/a.gif"})
    web.pages["https://c/a.gif"] = (200, GIF, {})
    folder = catalog.thumbs_dir(st.data, st.settings)
    r = anim_rows(st)["youtube a"]

    async def go():
        w = cd.DetailWorker(st)
        catalog.remove_items(st.db, [r["id"]], folder)                                   # zmizí dřív, než se animace uloží
        await w._anim_one({"id": r["id"], "anim_url": "https://c/a.gif"})
    asyncio.run(go())
    assert not list(folder.glob("*.anim.*")) and anim_rows(st)["youtube a"]["anim_file"] is None


# ------------------------------------------------------------ mazání souborů
def put_anim(st, key, name=None):
    folder = catalog.thumbs_dir(st.data, st.settings)
    folder.mkdir(parents=True, exist_ok=True)
    r = anim_rows(st)[key]
    name = name or f"{r['id']}.anim.mp4"
    (folder / name).write_bytes(MP4)
    with st.db.conn() as c:
        c.execute("update catalog_items set anim_file=? where id=?", (name, r["id"]))
    return folder, name


def test_animation_files_are_removed_with_the_item_source_and_after_download(st, fake, info):
    make(st, fake, [e("a"), e("b"), e("c")])
    fa, na = put_anim(st, "youtube a")
    put_anim(st, "youtube b")
    put_anim(st, "youtube c")
    a, b, c_ = (anim_rows(st)[k]["id"] for k in ("youtube a", "youtube b", "youtube c"))
    catalog.remove_items(st.db, [a], fa)
    assert not (fa / na).exists() and anim_rows(st)["youtube a"]["anim_file"] is None
    # stažení: položka ve frontě → hotovo
    with st.db.conn() as cx:
        j = cx.execute("insert into jobs(url, status, source, pos, created_at, updated_at) values('u','done','catalog',1,1,1)").lastrowid
        cx.execute("update catalog_items set state='queued', job_id=? where id=?", (j, b))
    assert catalog.reconcile(st.db, fa)["done"] == 1
    assert not (fa / f"{b}.anim.mp4").exists() and anim_rows(st)["youtube b"]["anim_file"] is None
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    assert (fa / f"{c_}.anim.mp4").exists()
    catalog.delete_source(st.db, sid, fa)
    assert not (fa / f"{c_}.anim.mp4").exists()


def test_remove_anim_ignores_unsafe_names(tmp_path):
    (tmp_path / "x.txt").write_text("a")
    catalog.remove_anim(tmp_path, "../x.txt")
    catalog.remove_anim(tmp_path, "x.txt")
    catalog.remove_anim(None, "1.anim.mp4")
    assert (tmp_path / "x.txt").exists()


# ------------------------------------------------------------ API
def test_api_serves_animation_and_reports_it_on_the_card(client):
    c, s = client
    from viddown.catalog import thumbs_dir
    s.db.query("select 1")
    with s.db.conn() as cx:
        cx.execute("insert into catalog_sources(id,url,status,added_at,title,folder) values (1,'https://s.example/p','done',1,'Z','Z')")
        cx.execute("insert into catalog_items(id,source_id,key,url,state,detail_state,added_at,updated_at,anim_file) values (3,1,'k','https://s.example/v','new','done',1,5,'3.anim.mp4')")
        cx.execute("insert into catalog_items(id,source_id,key,url,state,detail_state,added_at,updated_at,anim_file) values (4,1,'k2','https://s.example/v2','new','done',1,5,'4.anim.gif')")
        cx.execute("insert into catalog_items(id,source_id,key,url,state,detail_state,added_at,updated_at) values (5,1,'k3','https://s.example/v3','new','done',1,5)")
    folder = thumbs_dir(s.data, s.settings)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "3.anim.mp4").write_bytes(MP4)
    (folder / "4.anim.gif").write_bytes(GIF)
    items = {i["id"]: i for i in c.get("/api/catalog/items").json()["items"]}
    assert items[3]["anim"] == "/api/catalog/anim/3?v=5" and items[3]["anim_kind"] == "video"
    assert items[4]["anim_kind"] == "image" and items[5]["anim"] is None and items[5]["anim_kind"] is None
    r = c.get("/api/catalog/anim/3")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and r.content == MP4
    assert c.get("/api/catalog/anim/4").headers["content-type"] == "image/gif"
    assert c.get("/api/catalog/anim/5").status_code == 404 and c.get("/api/catalog/anim/999").status_code == 404
    with s.db.conn() as cx:
        cx.execute("update catalog_items set anim_file='../../etc/passwd' where id=5")
    assert c.get("/api/catalog/anim/5").status_code == 404                                  # nebezpečný název se nikdy neotevře


# ------------------------------------------------------------ nastavení a migrace 9
def test_anim_settings_defaults_and_validation(data):
    assert DEFAULTS["catalog_anim"] is False and DEFAULTS["catalog_anim_max_mb"] == 3
    s = Settings()
    s.update({"catalog_anim": True, "catalog_anim_max_mb": 10})
    assert s.get("catalog_anim") is True and s.get("catalog_anim_max_mb") == 10
    for bad in (0, 21, -1):
        with pytest.raises(ValueError):
            s.update({"catalog_anim_max_mb": bad})


def test_migration_9_adds_columns_and_keeps_data(tmp_path):
    from viddown import db as dbm
    p = tmp_path / "v8.db"
    c = sqlite3.connect(p)
    for ver, step in dbm.MIGRATIONS[:8]:
        if isinstance(step, str):
            for sql in dbm._split_sql(step):
                c.execute(sql)
        else:
            step(c)
    c.execute("pragma user_version=8")
    c.execute("insert into catalog_sources(id,url,status,added_at) values (1,'https://s.example',  'done', 1)")
    c.execute("insert into catalog_items(source_id,key,url,added_at,updated_at,thumb_url) values (1,'k','https://s.example/v',1,1,'https://i/x.jpg')")
    c.commit()
    c.close()
    d = DB(p)
    assert d.schema_version == dbm.MIGRATIONS[-1][0] >= 9
    cols = {r["name"] for r in d.query("pragma table_info(catalog_items)")}
    assert {"anim_url", "anim_file"} <= cols
    assert "catalog_items_noanim" in {r["name"] for r in d.query("select name from sqlite_master where type='index'")}
    r = d.query("select thumb_url, anim_url, anim_file from catalog_items")[0]
    assert (r["thumb_url"], r["anim_url"], r["anim_file"]) == ("https://i/x.jpg", None, None)
    assert (tmp_path / "v8.db.v8.bak").exists()


# ------------------------------------------------------------ miniatury za ochranou proti hotlinku (Referer)
def test_referer_of():
    from viddown import thumbs
    assert thumbs.referer_of("https://web.example/a/b?c=1") == "https://web.example/"
    assert thumbs.referer_of("http://x.example:8080/v") == "http://x.example:8080/"
    assert thumbs.referer_of("") is None and thumbs.referer_of(None) is None and thumbs.referer_of("ftp://x/y") is None


def test_thumbnails_and_animations_are_fetched_with_the_page_as_referer(st, fake, info, images):
    make(st, fake, [e("a", thumbnail="https://cdn.example/a.jpg")])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done', anim_url='https://cdn.example/a.gif'")
    seen = {}

    def handler(req):
        seen["ua"], seen["ref"] = req.headers.get("user-agent"), req.headers.get("referer")
        return httpx.Response(200, content=GIF)
    real = cd.httpx.Client
    cd.httpx.Client = lambda *a, **kw: real(*a, transport=httpx.MockTransport(handler), **kw)
    try:
        asyncio.run(run_until(st, lambda: anim_rows(st)["youtube a"]["anim_file"] and anim_rows(st)["youtube a"]["thumb_file"], thumbs=True))
    finally:
        cd.httpx.Client = real
    assert images.referers and set(images.referers) == {"https://example.com/"}               # adresa videa e() je example.com
    assert seen["ref"] == "https://example.com/" and "Chrome" in seen["ua"]


def test_thumbs_fetch_sends_referer_and_browser_agent(tmp_path, monkeypatch):
    from viddown import thumbs
    seen = {}

    def handler(req):
        seen.update(ua=req.headers.get("user-agent"), ref=req.headers.get("referer"))
        return httpx.Response(200 if req.headers.get("referer") else 403, content=JPEG)
    real = httpx.Client
    monkeypatch.setattr(thumbs.httpx, "Client", lambda *a, **kw: real(*a, transport=httpx.MockTransport(handler), **kw))
    assert REAL_THUMB_FETCH("https://cdn.example/x.jpg", tmp_path / "a") is False              # bez Referer CDN odmítne (403)
    assert REAL_THUMB_FETCH("https://cdn.example/x.jpg", tmp_path / "b", referer="https://web.example/") is True
    assert seen["ref"] == "https://web.example/" and "Chrome" in seen["ua"]


def test_failed_thumbnails_can_be_retried(st, fake, info, images):
    make(st, fake, [e("a", thumbnail="https://img.example/bad.jpg"), e("b", thumbnail="https://img.example/b.jpg")])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")
    asyncio.run(run_until(st, lambda: all(r["thumb_file"] is not None for r in anim_rows(st).values()), thumbs=True))
    assert anim_rows(st)["youtube a"]["thumb_file"] == "" and cd.DetailWorker(st).status()["thumbs_failed"] == 1
    with st.db.conn() as c:
        c.execute("update catalog_items set thumb_url='https://img.example/a.jpg' where key='youtube a'")     # web už miniaturu pustí
    assert cd.retry_failed(st.db)["thumbs"] == 1
    asyncio.run(run_until(st, lambda: anim_rows(st)["youtube a"]["thumb_file"], thumbs=True))
    assert anim_rows(st)["youtube a"]["thumb_file"].endswith(".jpg") and cd.DetailWorker(st).status()["thumbs_failed"] == 0
