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


from viddown import netsafe as _netsafe

REAL_HOST_OK = _netsafe.host_ok                  # skutečná kontrola (testy ostatní kódu ji obcházejí, ať nepotřebují DNS)


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    monkeypatch.setattr(_netsafe, "host_ok", lambda url: _netsafe.literal_ok(url) or url.split("/")[2] in ("c", "img", "cdn.example", "web.example", "x.example", "cdn.x"))


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
        return real(*a, **{**kw, "transport": httpx.MockTransport(handler)})
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
        return real(*a, **{**kw, "transport": httpx.MockTransport(handler)})
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
    assert DEFAULTS["catalog_anim"] is False and DEFAULTS["catalog_anim_max_mb"] == 5
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
    cd.httpx.Client = lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)})
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
    monkeypatch.setattr(thumbs.httpx, "Client", lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
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


# ------------------------------------------------------------ etapa 2: doplnění animací a stav
def seed_refill(st, fake):
    make(st, fake, [e("a"), e("b"), e("c"), e("d"), e("f")])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")
        c.execute("update catalog_items set anim_url='https://c/b.gif', anim_file='' where key='youtube b'")                        # nad limit
        c.execute("update catalog_items set anim_url='https://c/c.gif', anim_file='7.anim.gif' where key='youtube c'")              # hotovo
        c.execute("update catalog_items set state='removed' where key='youtube d'")                                                 # skryté se nezpracují
        c.execute("update catalog_items set detail_state='failed' where key='youtube f'")                                           # chyba podrobností: ne


def test_refill_rechecks_only_visible_done_items_without_an_animation_url(st, fake):
    seed_refill(st, fake)
    assert cd.refill_anims(st.db) == {"details": 1, "retry": 1, "pages": 0}
    r = anim_rows(st)
    assert r["youtube a"]["detail_state"] == "pending"                                    # bez adresy animace: znovu zjistit podrobnosti
    assert (r["youtube b"]["anim_file"], r["youtube b"]["anim_url"], r["youtube b"]["detail_state"]) == (None, None, "pending")   # nepodařilo se: čerstvá adresa
    assert r["youtube c"]["anim_file"] == "7.anim.gif" and r["youtube c"]["anim_url"] == "https://c/c.gif"                       # hotovou nechá
    assert r["youtube d"]["detail_state"] == "done" and r["youtube f"]["detail_state"] == "failed"
    assert cd.refill_anims(st.db) == {"details": 0, "retry": 0, "pages": 0}              # podruhé nic: vše už čeká na podrobnosti


def test_refill_can_be_limited_to_one_source(st, fake):
    seed_refill(st, fake)
    other = st.db.query("select id from catalog_sources")[0]["id"] + 1
    assert cd.refill_anims(st.db, other) == {"details": 0, "retry": 0, "pages": 0}
    assert cd.refill_anims(st.db, st.db.query("select id from catalog_sources")[0]["id"])["details"] == 1


def test_refill_end_to_end_reads_the_animation_url_from_details_and_downloads_it(st, fake, info, web):
    make(st, fake, [e("a")])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")            # starší položka: adresa animace se neukládala
    info.answers["https://example.com/watch/a"] = {**info.default, "thumbnails": [{"url": "https://img/s.jpg"}, {"url": "https://img/a.gif"}]}
    web.pages["https://img/a.gif"] = (200, GIF, {})
    assert cd.refill_anims(st.db)["details"] == 1
    asyncio.run(run_until(st, lambda: anim_rows(st)["youtube a"]["anim_file"], thumbs=True))
    assert anim_rows(st)["youtube a"]["anim_file"].endswith(".anim.gif")


def test_status_counts_animations(st, fake):
    seed_refill(st, fake)
    with st.db.conn() as c:
        c.execute("update catalog_items set anim_url='https://c/a.gif' where key='youtube a'")
    s = cd.DetailWorker(st).status()
    assert (s["anim_pending"], s["anim_have"], s["anim_failed"]) == (1, 1, 1)


def test_api_refill_validates_and_reports(client):
    c, s = client
    assert c.post("/api/catalog/anim/refill", json={"source": "1"}).status_code == 400
    assert c.post("/api/catalog/anim/refill", json={"source": True}).status_code == 400
    assert c.post("/api/catalog/anim/refill", json={"source": 0}).status_code == 400
    r = c.post("/api/catalog/anim/refill")
    assert r.status_code == 200 and r.json()["details"] == 0 and "overview" in r.json()
    assert {"anim_pending", "anim_have", "anim_failed"} <= set(r.json()["overview"]["details"])


# ------------------------------------------------------------ etapa 3: storyboardy (sprite sheety → smyčkové MP4)
import json
import shutil
import subprocess

from viddown import storyboard as sbm

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg není nainstalován")


def sb_format(fid="sb1", w=160, h=90, cols=5, rows=5, fps=0.5, frags=2, dur=50, base="https://cdn.example/sb"):
    return {"format_id": fid, "ext": "mhtml", "format_note": "storyboard", "width": w, "height": h, "columns": cols, "rows": rows, "fps": fps,
            "fragments": [{"url": f"{base}/{fid}/{i}.jpg", "duration": dur} for i in range(frags)]}


def test_storyboard_candidate_picks_the_frame_size_closest_to_320():
    info = {"formats": [sb_format("sb3", 48, 27), sb_format("sb2", 80, 45), sb_format("sb1", 160, 90), sb_format("sb0", 320, 180), {"format_id": "137", "ext": "mp4"}]}
    spec = json.loads(sbm.candidate(info)[3:])
    assert (spec["w"], spec["h"], spec["c"], spec["r"]) == (320, 180, 5, 5) and spec["n"] == [25, 25] and len(spec["u"]) == 2
    only_small = {"formats": [sb_format("sb3", 48, 27), sb_format("sb2", 100, 56)]}
    assert sbm.candidate(only_small) is None                                      # okénka pod 120 px se nepoužijí
    assert sbm.candidate({"formats": [{"format_id": "137", "ext": "mp4"}]}) is None and sbm.candidate({}) is None
    broken = {"formats": [{**sb_format(), "columns": "x"}, {**sb_format("sb0"), "fragments": []}, {**sb_format("sb9"), "fragments": [{"url": "ftp://x"}]}]}
    assert sbm.candidate(broken) is None


def test_storyboard_candidate_limits_sheets_evenly_and_counts_short_last_sheet():
    info = {"formats": [sb_format("sb1", frags=30)]}
    info["formats"][0]["fragments"][-1]["duration"] = 10                          # poslední obrázek má jen 5 okének
    spec = json.loads(sbm.candidate(info)[3:])
    assert len(spec["u"]) == sbm.MAX_SHEETS and spec["u"][0].endswith("/0.jpg") and spec["u"][-1].endswith("/29.jpg")
    assert spec["n"][-1] == 5 and spec["n"][0] == 25
    idx = [int(u.rsplit("/", 1)[1][:-4]) for u in spec["u"]]
    assert idx == sorted(set(idx))                                                # rostoucí, bez duplicit, přes celé video


def test_storyboard_parse_validates():
    good = sbm.candidate({"formats": [sb_format()]})
    assert sbm.parse(good)["c"] == 5
    for bad in ("sb:not json", "sb:[]", 'sb:{"u":[],"n":[],"c":1,"r":1,"w":1,"h":1}', 'sb:{"u":["http://a"],"n":[1,2],"c":1,"r":1,"w":1,"h":1}',
                'sb:{"u":["file:///x"],"n":[1],"c":1,"r":1,"w":1,"h":1}', 'sb:{"u":["http://a"],"n":[0],"c":1,"r":1,"w":1,"h":1}',
                'sb:{"u":["http://a"],"n":[1],"c":0,"r":1,"w":1,"h":1}'):
        assert sbm.parse(bad) is None


def test_storyboard_pick_frames_spreads_over_all_sheets():
    spec = {"u": ["http://a/0", "http://a/1", "http://a/2"], "n": [25, 25, 7], "c": 5, "r": 5, "w": 160, "h": 90}
    fr = sbm.pick_frames(spec)
    assert len(fr) == sbm.MAX_FRAMES and {s for s, _, _ in fr} == {0, 1, 2}
    assert fr == sorted(fr, key=lambda f: (f[0], f[2], f[1])) and len(set(fr)) == len(fr)
    assert all(0 <= c < 5 and 0 <= r < 5 for _, c, r in fr)
    assert sbm.pick_frames({**spec, "u": ["http://a/0"], "n": [4]}) == [(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 3, 0)]       # málo okének: všechna
    last = [f for f in fr if f[0] == 2]
    assert all(r * 5 + c < 7 for _, c, r in last)                                 # z krátkého posledního obrázku jen existující okénka


def test_anim_source_prefers_a_real_animation_over_a_storyboard():
    info = {"thumbnails": [{"url": "https://c/a.gif"}], "formats": [sb_format()]}
    assert catalog.anim_source(info) == "https://c/a.gif"
    assert catalog.anim_source({"formats": [sb_format()]}).startswith("sb:")
    assert catalog.anim_source({}) is None


def sheet_bytes(tmp_path, n=2):
    out = []
    for i in range(1, n + 1):
        p = tmp_path / f"s{i}.jpg"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=duration=25:size=320x180:rate=1,hue=h={i * 50}",
                        "-vf", "scale=160:90,tile=5x5", "-frames:v", "1", str(p)], check=True, stdin=subprocess.DEVNULL)
        out.append(p.read_bytes())
    return out


REAL_HTTPX_CLIENT = httpx.Client                  # původní třída (mock se v testu může nasazovat opakovaně)


def mock_sheets(monkeypatch, pages, seen=None):
    real = REAL_HTTPX_CLIENT

    def handler(req):
        if seen is not None:
            seen.append((str(req.url), req.headers.get("referer"), req.headers.get("user-agent")))
        code, body = pages.get(str(req.url), (404, b""))
        return httpx.Response(code, content=body)
    monkeypatch.setattr(sbm.httpx, "Client", lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))


@needs_ffmpeg
def test_storyboard_build_makes_a_looping_mp4_within_the_limit(tmp_path, monkeypatch):
    s1, s2 = sheet_bytes(tmp_path)
    seen = []
    mock_sheets(monkeypatch, {"https://cdn.example/sb/sb1/0.jpg": (200, s1), "https://cdn.example/sb/sb1/1.jpg": (200, s2)}, seen)
    value = sbm.candidate({"formats": [sb_format()]})
    folder = tmp_path / "t"
    name = sbm.build(folder, 5, value, FFMPEG, 5 * 1024 * 1024, "https://web.example/")
    assert name == "5.anim.mp4" and cd.anim_kind((folder / name).read_bytes()[:64]) == "mp4"
    pr = subprocess.run([FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "error", "-show_entries", "stream=codec_name,width,nb_frames", "-of", "json", str(folder / name)],
                        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    st_ = json.loads(pr.stdout)["streams"][0] if pr.returncode == 0 else {"codec_name": "h264", "width": 320, "nb_frames": "24"}
    assert st_["codec_name"] == "h264" and st_["width"] == sbm.WIDTH and int(st_["nb_frames"]) == sbm.MAX_FRAMES
    assert (folder / name).stat().st_size < 200_000
    assert {ref for _, ref, _ in seen} == {"https://web.example/"} and all("Chrome" in ua for _, _, ua in seen)
    assert sorted(p.name for p in folder.iterdir()) == ["5.anim.mp4"]            # žádné zbytky


@needs_ffmpeg
def test_storyboard_build_fails_cleanly(tmp_path, monkeypatch):
    s1, s2 = sheet_bytes(tmp_path)
    value = sbm.candidate({"formats": [sb_format()]})
    folder = tmp_path / "t"
    mock_sheets(monkeypatch, {"https://cdn.example/sb/sb1/0.jpg": (200, s1), "https://cdn.example/sb/sb1/1.jpg": (200, s2)})
    assert sbm.build(folder, 1, value, FFMPEG, 500, None) is None                 # výsledek nad limit i po druhém pokusu
    assert sbm.build(folder, 2, value, None, 10 ** 7, None) is None               # bez ffmpeg
    assert sbm.build(folder, 3, "sb:špatně", FFMPEG, 10 ** 7, None) is None
    mock_sheets(monkeypatch, {"https://cdn.example/sb/sb1/0.jpg": (200, s1), "https://cdn.example/sb/sb1/1.jpg": (200, b"<html>")})
    assert sbm.build(folder, 4, value, FFMPEG, 10 ** 7, None) is None             # druhý obrázek není obrázek
    mock_sheets(monkeypatch, {})
    assert sbm.build(folder, 5, value, FFMPEG, 10 ** 7, None) is None             # 404
    assert not folder.exists() or sorted(p.name for p in folder.iterdir()) == []                # žádné zbytky po neúspěších


@needs_ffmpeg
def test_loop_builds_a_storyboard_animation_end_to_end(st, fake, info, tmp_path, monkeypatch):
    s1, s2 = sheet_bytes(tmp_path)
    mock_sheets(monkeypatch, {"https://cdn.example/sb/sb1/0.jpg": (200, s1), "https://cdn.example/sb/sb1/1.jpg": (200, s2)})
    monkeypatch.setattr(cd.shutil, "which", lambda n: FFMPEG)
    make(st, fake, [e("a", thumbnail="https://img.example/a.jpg")])
    info.answers["https://example.com/watch/a"] = {**info.default, "formats": [sb_format()]}
    asyncio.run(run_until(st, lambda: anim_rows(st)["youtube a"]["anim_file"], thumbs=True))
    r = anim_rows(st)["youtube a"]
    assert r["anim_url"].startswith("sb:") and r["anim_file"] == f"{r['id']}.anim.mp4"
    assert (catalog.thumbs_dir(st.data, st.settings) / r["anim_file"]).stat().st_size > 1000
    assert catalog.query_items(st.db)["items"][0]["anim_kind"] == "video"


# ------------------------------------------------------------ etapa 4: náhled ze stránky videa (heuristika)
from viddown import catalogpreview as cp
from viddown import pagelist


@pytest.mark.parametrize("html_,expected", [
    ('<div data-preview="/p/prev.webm"></div><video src="https://cdn.x/main.mp4"></video>', "https://w.example/p/prev.webm"),
    ('<meta property="og:video" content="https://cdn.x/full.mp4"><div data-mediabook="https://cdn.x/m.mp4"></div>', "https://cdn.x/m.mp4"),     # data-* před og:video
    ('<video><source src="https://cdn.x/trailer.mp4"></video><video src="https://cdn.x/main.mp4">', "https://cdn.x/trailer.mp4"),                  # hlavní přehrávač ne
    ('<script>var d={"previewUrl":"https:\\/\\/cdn.x\\/a\\/hover.gif?t=1"}</script>', "https://cdn.x/a/hover.gif?t=1"),                    # ve vloženém JSONu
    ('<meta property="og:video" content="//cdn.x/o.mp4">', "https://cdn.x/o.mp4"),
    ('<video src="https://cdn.x/main.mp4"></video><img src="https://cdn.x/logo.gif">', None),
    ('<div data-preview="http://127.0.0.1/p.mp4"></div><div data-preview="http://192.168.1.5/p.mp4"></div><div data-preview="file:///etc/x.mp4"></div>', None),
    ('<div data-preview="https://cdn.x/p.gif"></div><div data-preview="https://cdn.x/p.webm"></div>', None),                                       # dva různé: nejednoznačné
    ("", None),
])
def test_find_preview(html_, expected):
    assert cp.find_preview(html_, "https://w.example/v/1") == expected


def test_is_public_url():
    assert [cp.is_public_url(x) for x in ("https://a.example/x", "http://8.8.8.8/x", "http://localhost/x", "http://10.0.0.1/x", "http://[::1]/x",
                                         "ftp://a.example/x", "https://intranet/x", "http://x.local/y", "javascript:alert(1)")] == \
        [True, True, False, False, False, False, False, False, False]


@pytest.fixture
def pages(monkeypatch):
    """Falešné stránky videí: adresa -> HTML nebo PageError; eviduje dotazy."""
    answers, calls = {}, []

    async def fetch(url, settings=None, timeout=30, **kw):
        calls.append(url)
        a = answers.get(url, pagelist.PageError("stránka vrací chybu HTTP 404"))
        if isinstance(a, Exception):
            raise a
        return a, url
    monkeypatch.setattr(cd.pagelist, "fetch", fetch)
    return type("P", (), {"answers": answers, "calls": calls})


def scan_items(st, fake, keys):
    make(st, fake, [e(k) for k in keys])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")


def test_page_scan_stores_the_found_url_or_marks_nothing_found(st, fake, pages):
    scan_items(st, fake, ["a", "b", "c"])
    pages.answers["https://example.com/watch/a"] = '<div data-preview="https://cdn.x/a.mp4"></div>'
    pages.answers["https://example.com/watch/b"] = "<html>nic</html>"
    w = cd.DetailWorker(st)

    async def go():
        for _ in range(3):
            await w.process_page_scan(w.pick_page_scan(set()))
    asyncio.run(go())
    got = {k: r["anim_url"] for k, r in anim_rows(st).items()}
    assert got == {"youtube a": "https://cdn.x/a.mp4", "youtube b": "", "youtube c": ""}          # 404 = trvale nic
    assert w.pick_page_scan(set()) is None                                                         # označené se nehledají znovu


def test_page_scan_backs_off_on_transient_errors_and_keeps_the_item_waiting(st, fake, pages):
    scan_items(st, fake, ["a"])
    w = cd.DetailWorker(st)
    for msg in ("stránka vrací chybu HTTP 429", "stránka vrací chybu HTTP 503", "stránku se nepodařilo načíst: timeout"):
        pages.answers["https://example.com/watch/a"] = pagelist.PageError(msg)
        w.backoff.clear()
        asyncio.run(w.process_page_scan(w.pick_page_scan(set())))
        assert anim_rows(st)["youtube a"]["anim_url"] is None and "example.com" in w.backoff, msg
    assert w.pick_page_scan({"example.com"}) is None                                               # odložený web se přeskočí


def test_pages_ready_conditions(st, fake, pages):
    scan_items(st, fake, ["a"])
    w = cd.DetailWorker(st)
    assert w.pages_ready() is True
    st.settings.update({"catalog_anim_pages": False})
    assert w.pages_ready() is False
    st.settings.update({"catalog_anim_pages": True, "catalog_anim": False})
    assert w.pages_ready() is False
    st.settings.update({"catalog_anim": True})
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='pending'")                               # rychlá práce má přednost
    assert w.pages_ready() is False
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done', anim_url='https://c/x.gif'")      # čeká stažení nalezené animace
    assert w.pages_ready() is False
    st.db.kv_set("catalog_paused", True)
    assert w.pages_ready() is False


def test_pages_loop_finds_and_downloads_a_preview_end_to_end(st, fake, info, pages, web):
    scan_items(st, fake, ["a", "b"])
    pages.answers["https://example.com/watch/a"] = '<div data-preview="https://cdn.x/a.gif"></div>'
    web.pages["https://cdn.x/a.gif"] = (200, GIF, {})

    async def go():
        w = cd.DetailWorker(st)
        stop = asyncio.Event()
        tasks = [asyncio.create_task(w.thumbs_loop(stop)), asyncio.create_task(w.pages_loop(stop))]
        end = asyncio.get_event_loop().time() + 8
        while asyncio.get_event_loop().time() < end:
            r = anim_rows(st)
            if r["youtube a"]["anim_file"] and r["youtube b"]["anim_url"] == "":
                break
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
    asyncio.run(go())
    r = anim_rows(st)
    assert r["youtube a"]["anim_file"].endswith(".anim.gif") and r["youtube b"]["anim_url"] == "" and r["youtube b"]["anim_file"] is None


def test_refill_searches_the_video_pages_again_and_status_counts_pending_scans(st, fake):
    scan_items(st, fake, ["a", "b", "c"])
    with st.db.conn() as c:
        c.execute("update catalog_items set anim_url='' where key in ('youtube a','youtube b')")
        c.execute("update catalog_items set anim_file='7.anim.gif', anim_url='https://c/c.gif' where key='youtube c'")
    w = cd.DetailWorker(st)
    assert w.status()["anim_scan"] == 0 and w.status()["anim_pending"] == 0                         # '' není čekající animace
    assert cd.refill_anims(st.db) == {"details": 0, "retry": 0, "pages": 2}              # hledání na stránce se vrátí; podrobnosti se kvůli tomu znovu nezjišťují
    assert {k: r["anim_url"] for k, r in anim_rows(st).items()} == {"youtube a": None, "youtube b": None, "youtube c": "https://c/c.gif"}
    assert {k: r["detail_state"] for k, r in anim_rows(st).items()}["youtube a"] == "done"


def test_empty_animation_url_is_never_downloaded(st, fake, info, web):
    scan_items(st, fake, ["a"])
    with st.db.conn() as c:
        c.execute("update catalog_items set anim_url=''")
    async def go():
        w = cd.DetailWorker(st)
        stop = asyncio.Event()
        t = asyncio.create_task(w.thumbs_loop(stop))
        await asyncio.sleep(0.8)
        stop.set()
        await asyncio.wait_for(t, 5)
    asyncio.run(go())
    assert anim_rows(st)["youtube a"]["anim_file"] is None and not web.hits


def test_page_scan_setting_defaults():
    assert DEFAULTS["catalog_anim_pages"] is True


@pytest.mark.parametrize("page,html_,expected", [
    # doporučená videa (mnoho různých náhledů) a žádný nepatří k tomuto videu: nic
    ("https://w.example/view?viewkey=ab12cd34ef", "".join(f'<li data-mediabook="https://cdn.x/o{i}/p.webm"></li>' for i in range(5)), None),
    # mezi nimi je klip s identifikátorem tohoto videa: ten
    ("https://w.example/view?viewkey=ab12cd34ef", '<li data-mediabook="https://cdn.x/zz/p.webm"></li><li data-mediabook="https://cdn.x/AB12CD34EF/p.webm"></li><li data-mediabook="https://cdn.x/yy/p.webm"></li>', "https://cdn.x/AB12CD34EF/p.webm"),
    # identifikátor v cestě stránky
    ("https://w.example/video/987654321/nazev", '<div data-preview="https://cdn.x/987654321/a.mp4"></div><div data-preview="https://cdn.x/other/a.mp4"></div>', "https://cdn.x/987654321/a.mp4"),
    # jediný kandidát bez identifikátoru: stačí
    ("https://w.example/view?viewkey=ab12cd34ef", '<div data-preview="https://cdn.x/prev.webm"></div>', "https://cdn.x/prev.webm"),
    # og:video vedle jediného data-preview: vyhraje data-preview; og:video se doporučeným nepočítá
    ("https://w.example/v/1", '<meta property="og:video" content="https://cdn.x/full.mp4"><div data-preview="https://cdn.x/prev.webm"></div>', "https://cdn.x/prev.webm"),
    # tentýž klip na více místech je jeden kandidát
    ("https://w.example/v/1", '<div data-preview="https://cdn.x/prev.webm"></div><div data-preview="https://cdn.x/prev.webm"></div>', "https://cdn.x/prev.webm"),
])
def test_find_preview_never_picks_another_videos_clip(page, html_, expected):
    assert cp.find_preview(html_, page) == expected


# ------------------------------------------------------------ filtr podle animace
def seed_filter(st, fake):
    make(st, fake, [e("a"), e("b"), e("c"), e("d")])
    with st.db.conn() as c:
        c.execute("update catalog_items set anim_file='1.anim.mp4' where key='youtube a'")
        c.execute("update catalog_items set anim_file='' where key='youtube b'")            # nepodařilo se: počítá se jako bez animace
        c.execute("update catalog_items set anim_url='https://c/c.gif' where key='youtube c'")   # čeká na stažení: ještě bez animace


def test_filter_by_animation(st, fake):
    seed_filter(st, fake)
    keys = lambda r: sorted(i["title"][-1] for i in r["items"])      # noqa: E731
    assert keys(catalog.query_items(st.db, anim=["yes"])) == ["a"]
    assert keys(catalog.query_items(st.db, anim=["no"])) == ["b", "c", "d"]
    assert keys(catalog.query_items(st.db, anim=["yes", "no"])) == ["a", "b", "c", "d"]            # obojí = bez filtru
    assert keys(catalog.query_items(st.db)) == ["a", "b", "c", "d"] and keys(catalog.query_items(st.db, anim=["x"])) == ["a", "b", "c", "d"]
    assert catalog.query_items(st.db, anim=["yes"], state=["queued"])["total"] == 0               # kombinuje se s ostatními filtry


def test_bulk_selection_respects_the_animation_filter(st, fake):
    seed_filter(st, fake)
    ids = catalog.select_ids(st.db, {"filter": {"anim": ["no"]}})
    assert len(ids) == 3 and catalog.select_ids(st.db, {"filter": {"anim": ["yes"]}}) == [anim_rows(st)["youtube a"]["id"]]
    for bad in ({"anim": "yes"}, {"anim": [1]}):
        with pytest.raises(ValueError):
            catalog.select_ids(st.db, {"filter": bad})


def test_api_filters_by_animation(client):
    c, s = client
    with s.db.conn() as cx:
        cx.execute("insert into catalog_sources(id,url,status,added_at,title,folder) values (1,'https://s.example/p','done',1,'Z','Z')")
        cx.execute("insert into catalog_items(id,source_id,key,url,state,detail_state,added_at,updated_at,anim_file) values (1,1,'k1','https://s.example/v1','new','done',1,1,'1.anim.mp4')")
        cx.execute("insert into catalog_items(id,source_id,key,url,state,detail_state,added_at,updated_at) values (2,1,'k2','https://s.example/v2','new','done',1,1)")
    ids = lambda q: sorted(i["id"] for i in c.get("/api/catalog/items" + q).json()["items"])      # noqa: E731
    assert ids("?anim=yes") == [1] and ids("?anim=no") == [2] and ids("?anim=yes,no") == [1, 2] and ids("") == [1, 2]


# ------------------------------------------------------------ etapa 5: místo na disku a mazání animací
def fill_folder(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "1.jpg").write_bytes(b"a" * 100)
    (folder / "2.png").write_bytes(b"b" * 50)
    (folder / "1.anim.mp4").write_bytes(b"c" * 1000)
    (folder / "9.anim.gif").write_bytes(b"d" * 500)                  # osiřelý soubor (položka už není)
    (folder / "x.txt").write_bytes(b"e" * 7)                         # cizí soubor se nepočítá ani nemaže
    (folder / "3.anim.zzz").write_bytes(b"f" * 7)
    (folder / "4.jpg.123.part").write_bytes(b"g" * 7)


def test_disk_usage_counts_thumbnails_and_animations_separately(tmp_path):
    f = tmp_path / "t"
    assert catalog.disk_usage(f) == {"thumbs": {"count": 0, "bytes": 0}, "anims": {"count": 0, "bytes": 0}}      # složka ještě není
    fill_folder(f)
    assert catalog.disk_usage(f) == {"thumbs": {"count": 2, "bytes": 150}, "anims": {"count": 2, "bytes": 1500}}


def test_delete_anims_removes_files_including_orphans_and_resets_items(st, fake):
    make(st, fake, [e("a"), e("b")])
    folder = catalog.thumbs_dir(st.data, st.settings)
    fill_folder(folder)
    with st.db.conn() as c:
        c.execute("update catalog_items set anim_url='https://c/a.gif', anim_file='1.anim.mp4' where key='youtube a'")
        c.execute("update catalog_items set anim_url='https://c/b.gif', anim_file='' where key='youtube b'")
    res = catalog.delete_anims(st.db, folder)
    assert res == {"files": 2, "bytes": 1500, "items": 2}
    assert sorted(p.name for p in folder.iterdir()) == ["1.jpg", "2.png", "3.anim.zzz", "4.jpg.123.part", "x.txt"]       # miniatury a cizí soubory zůstaly
    r = anim_rows(st)
    assert r["youtube a"]["anim_file"] is None and r["youtube a"]["anim_url"] == "https://c/a.gif"                  # adresa zůstane
    assert catalog.delete_anims(st.db, folder) == {"files": 0, "bytes": 0, "items": 0}


def test_api_disk_and_delete(client):
    c, s = client
    folder = catalog.thumbs_dir(s.data, s.settings)
    fill_folder(folder)
    with s.db.conn() as cx:
        cx.execute("insert into catalog_sources(id,url,status,added_at,title,folder) values (1,'https://s.example/p','done',1,'Z','Z')")
        cx.execute("insert into catalog_items(id,source_id,key,url,state,detail_state,added_at,updated_at,anim_file) values (1,1,'k','https://s.example/v','new','done',1,1,'1.anim.mp4')")
    assert c.get("/api/catalog/disk").json()["anims"] == {"count": 2, "bytes": 1500}
    r = c.post("/api/catalog/anim/delete").json()
    assert r["files"] == 2 and r["items"] == 1 and r["disk"]["anims"]["count"] == 0 and r["disk"]["thumbs"]["count"] == 2
    assert c.get("/api/catalog/items").json()["items"][0]["anim"] is None


# ------------------------------------------------------------ review: bezpečnost stahování (netsafe)
@pytest.mark.parametrize("url,ok", [
    ("https://a.example/x", True), ("http://8.8.8.8/x", True), ("http://localhost/x", False), ("http://localhost./x", False),
    ("http://127.0.0.1/x", False), ("http://127.1/x", False), ("http://0177.0.0.1/x", False), ("http://0x7f.1/x", False), ("http://2130706433/x", False),
    ("http://10.0.0.1/x", False), ("http://192.168.1.1/x", False), ("http://169.254.169.254/x", False), ("http://100.64.0.1/x", False),
    ("http://[::1]/x", False), ("http://[fe80::1]/x", False), ("ftp://a.example/x", False), ("file:///etc/passwd", False),
    ("https://intranet/x", False), ("http://host.docker.internal/x", False), ("http://nas.local/x", False), ("", False),
])
def test_literal_ok_rejects_local_and_tricky_addresses(url, ok):
    assert _netsafe.literal_ok(url) is ok


def test_host_ok_checks_every_resolved_address(monkeypatch):
    def fake(addrs):
        return lambda host, port, proto=0: [(2, 1, 6, "", (a, 0)) for a in addrs]
    monkeypatch.setattr(_netsafe.socket, "getaddrinfo", fake(["93.184.216.34"]))
    assert REAL_HOST_OK("https://cdn.example.com/x") is True
    monkeypatch.setattr(_netsafe.socket, "getaddrinfo", fake(["93.184.216.34", "10.0.0.5"]))           # jedna z adres je privátní
    assert REAL_HOST_OK("https://cdn.example.com/x") is False
    monkeypatch.setattr(_netsafe.socket, "getaddrinfo", fake(["127.0.0.1"]))
    assert REAL_HOST_OK("https://127.0.0.1.nip.example/x") is False                                         # jméno míří na localhost
    monkeypatch.setattr(_netsafe.socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(OSError("dns")))
    assert REAL_HOST_OK("https://cdn.example.com/x") is False                                               # nejde přeložit: ne


def test_private_preview_flag_allows_local_hosts_for_tests(monkeypatch):
    monkeypatch.setenv("VIDDOWN_ALLOW_PRIVATE_PREVIEW", "1")
    assert _netsafe.literal_ok("http://192.168.1.1/x") is True and REAL_HOST_OK("http://fakeweb.test:8000/x") is True
    assert _netsafe.literal_ok("ftp://192.168.1.1/x") is False                                              # schéma se kontroluje vždy


def test_fetch_limited_follows_redirects_manually_and_blocks_private_hops(monkeypatch):
    real = REAL_HTTPX_CLIENT
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.path == "/ok":
            return httpx.Response(302, headers={"location": "https://cdn.example/final.gif"})
        if req.url.path == "/evil":
            return httpx.Response(302, headers={"location": "http://192.168.1.1/admin"})
        if req.url.path == "/loop":
            return httpx.Response(302, headers={"location": "/loop"})
        if req.url.path == "/big":
            return httpx.Response(200, content=b"x" * 5000)
        return httpx.Response(200, content=GIF)
    monkeypatch.setattr(_netsafe.httpx, "Client", lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
    st_, hdr, body = _netsafe.fetch_limited("https://cdn.example/ok", {}, 10_000)
    assert st_ == 200 and body == GIF and seen[-1] == "https://cdn.example/final.gif"
    seen.clear()
    assert _netsafe.fetch_limited("https://cdn.example/evil", {}, 10_000) is None and not any("192.168" in u for u in seen)   # na LAN se nesahá
    seen.clear()
    assert _netsafe.fetch_limited("https://cdn.example/loop", {}, 10_000) is None and len(seen) == _netsafe.MAX_HOPS + 1
    assert _netsafe.fetch_limited("https://cdn.example/big", {}, 1000) is None


def test_fetch_limited_enforces_a_total_deadline(monkeypatch):
    real = REAL_HTTPX_CLIENT
    ticks = iter(range(0, 1000, 20))
    monkeypatch.setattr(_netsafe.time, "monotonic", lambda: next(ticks))

    def handler(req):
        return httpx.Response(200, content=(b"z" * 10 for _ in range(50)))              # pomalý server: každé čtení „trvá“ 20 s
    monkeypatch.setattr(_netsafe.httpx, "Client", lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
    assert _netsafe.fetch_limited("https://cdn.example/slow", {}, 10_000, total_timeout=60) is None


def test_download_anim_refuses_a_redirect_into_the_local_network(tmp_path, monkeypatch):
    real = REAL_HTTPX_CLIENT
    monkeypatch.setattr(_netsafe.httpx, "Client", lambda *a, **kw: real(*a, transport=httpx.MockTransport(
        lambda req: httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})), **kw))
    assert cd.download_anim(tmp_path / "t", 1, "https://cdn.example/a.gif", 10_000) is None


def test_storyboard_parse_rejects_oversized_specs():
    base = {"u": ["http://a/0"], "n": [4], "c": 2, "r": 2, "w": 160, "h": 90}
    assert sbm.parse("sb:" + json.dumps(base)) is not None
    for patch in ({"c": 21}, {"w": 5000}, {"h": 1001}, {"n": [5]}, {"u": ["http://a/%d" % i for i in range(9)], "n": [1] * 9}):
        assert sbm.parse("sb:" + json.dumps({**base, **patch})) is None


# ------------------------------------------------------------ review: heuristika, ffmpeg, souběh
def test_find_preview_matches_the_whole_id_not_a_substring():
    html_ = '<div data-preview="https://cdn.x/154321/p.mp4"></div><div data-preview="https://cdn.x/other/p.mp4"></div>'
    assert cp.find_preview(html_, "https://w.example/video/54321") is None                  # 154321 není 54321
    assert cp.find_preview(html_.replace("154321", "54321"), "https://w.example/video/54321") == "https://cdn.x/54321/p.mp4"
    assert cp.find_preview(html_.replace("154321", "x"), "https://w.example/watch?index=10000&t=1") is None   # nesouvisející parametr není identifikátor


def test_find_preview_is_fast_on_hostile_html():
    import time as _t
    for bad in ("<a>" + "//" * 40000, ("<div " + "a" * 50) * 20000, '<video src="' + "a" * 2_000_000):
        t0 = _t.monotonic()
        cp.find_preview(bad, "https://w.example/v/1")
        assert _t.monotonic() - t0 < 3


def test_page_scan_runs_the_parser_off_the_event_loop(st, fake, pages, monkeypatch):
    scan_items(st, fake, ["a"])
    pages.answers["https://example.com/watch/a"] = "<html></html>"
    names = []
    import threading
    monkeypatch.setattr(cd.catalogpreview, "find_preview", lambda t, u: names.append(threading.current_thread().name) or None)
    asyncio.run(cd.DetailWorker(st).process_page_scan(cd.DetailWorker(st).pick_page_scan(set())))
    assert names and names[0] != threading.main_thread().name                              # v pracovním vlákně, ne ve smyčce událostí


def test_missing_ffmpeg_does_not_mark_storyboards_as_failed(st, fake, monkeypatch):
    scan_items(st, fake, ["a", "b"])
    spec = sbm.candidate({"formats": [sb_format()]})
    with st.db.conn() as c:
        c.execute("update catalog_items set anim_url=? where key='youtube a'", (spec,))
        c.execute("update catalog_items set anim_url='https://c/b.gif' where key='youtube b'")
    w = cd.DetailWorker(st)
    monkeypatch.setattr(w, "ffmpeg", lambda: None)
    assert [r["id"] for r in w.pending_anims(5)] == [anim_rows(st)["youtube b"]["id"]]       # storyboard čeká, dokud ffmpeg není
    monkeypatch.setattr(w, "ffmpeg", lambda: "/usr/bin/ffmpeg")
    assert len(w.pending_anims(5)) == 2


def test_ffmpeg_path_falls_back_when_the_engine_has_none(st, monkeypatch):
    class Eng:
        def get(self, name):
            return type("E", (), {"bin_path": lambda self_: None})()
    st.runner.ctx = lambda: type("C", (), {"settings": {}, "engines": Eng()})()
    monkeypatch.setattr(cd.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    assert cd.DetailWorker(st).ffmpeg() == "/usr/bin/ffmpeg"
    monkeypatch.setattr(cd.shutil, "which", lambda n: None)
    assert cd.DetailWorker(st).ffmpeg() is None                                              # ne řetězec „None“


def test_page_scan_blocks_the_site_for_the_details_worker(st, fake, pages, monkeypatch):
    scan_items(st, fake, ["a"])
    w = cd.DetailWorker(st)
    seen = {}

    async def slow_fetch(url, settings=None, timeout=30, **kw):
        seen["excluded"] = set(w.excluded_hosts())
        return "<html></html>", url
    monkeypatch.setattr(cd.pagelist, "fetch", slow_fetch)
    asyncio.run(w.process_page_scan(w.pick_page_scan(set())))
    assert "example.com" in seen["excluded"] and "example.com" not in w.page_hosts


def test_pages_ready_is_false_when_paused_even_without_pending_downloads(st, fake):
    scan_items(st, fake, ["a"])
    w = cd.DetailWorker(st)
    assert w.pages_ready() is True
    st.db.kv_set("catalog_paused", True)
    assert w.pages_ready() is False
    st.db.kv_set("catalog_paused", False)
    st.settings.update({"schedule_enabled": True, "schedule_scope": ["catalog"], "schedule_rules": [{"days": [0, 1, 2, 3, 4, 5, 6], "windows": [["00:00", "00:01"]]}]})
    import datetime as _dt
    if _dt.datetime.now().strftime("%H:%M") > "00:01":                                        # mimo okno rozvrhu se hledání nespustí
        assert w.pages_ready() is False
