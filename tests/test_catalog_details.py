"""Katalog, etapa 2: podrobnosti (rozlišení, velikost, délka), miniatury, pauzy po webech, odkládání a pozastavení."""
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_catalog import client, e, fake, playlist, rt, scan  # noqa: F401
from viddown import catalog, catalogdetails as cd
from viddown.config import Settings
from viddown.db import DB
from viddown.resolvers import ResolveError

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200


class St:
    def __init__(self, data):
        self.data = data
        self.db = DB(data / "viddown.db")
        self.settings = Settings()
        self.settings.update({"catalog_gap": 0})
        self.runner = SimpleNamespace(ctx=lambda: SimpleNamespace(settings=self.settings.all()))


@pytest.fixture
def st(data):
    return St(data)


@pytest.fixture
def info(monkeypatch):
    """Podvržené yt-dlp: full_info vrací odpověď podle adresy (nebo vyhodí výjimku) a eviduje volání."""
    calls, answers, ctxs = [], {}, []
    default = {"title": "Zjištěno", "duration": 120, "requested_formats": [{"height": 1080, "filesize": 100}, {"filesize": 50}],
               "thumbnails": [{"url": "https://img.example/small.jpg", "width": 120, "height": 90},
                              {"url": "https://img.example/max.jpg", "width": 1280, "height": 720}]}
    delay = {"s": 0.0}

    async def full_info(url, ctx, timeout=180):
        calls.append((url, time.monotonic()))
        ctxs.append(ctx)
        if delay["s"]:
            await asyncio.sleep(delay["s"])
        a = answers.get(url, default)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(cd.ytdlp, "full_info", full_info)
    return SimpleNamespace(calls=calls, answers=answers, ctxs=ctxs, delay=delay, default=default)


@pytest.fixture(autouse=True)
def images(monkeypatch):
    """Podvržené stažení obrázku: adresy s „bad“ selžou, „html“ vrátí stránku, „png“ vrátí PNG, ostatní JPEG."""
    class Fetched(list):
        referers: list = []

    fetched = Fetched()
    fetched.referers = []

    def fetch(url, dest, timeout=20, referer=None, proxy=None):
        fetched.append(url)
        fetched.referers.append(referer)
        if "bad" in url:
            return False
        dest.write_bytes(b"<html>chyba</html>" if "html" in url else (PNG if url.endswith(".png") else JPEG))
        return True
    monkeypatch.setattr(cd.thumbs, "fetch", fetch)
    return fetched


async def run_until(st, cond, timeout=8, thumbs=False, worker=None):
    w = worker or cd.DetailWorker(st)
    stop = asyncio.Event()
    tasks = [asyncio.create_task(w.run(stop))]
    if thumbs:
        tasks.append(asyncio.create_task(w.thumbs_loop(stop)))
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        await asyncio.sleep(0.02)
    ok = cond()
    stop.set()
    await asyncio.wait_for(asyncio.gather(*tasks), 5)
    assert ok, "podmínka nenastala včas"
    return w


def make(st, fake, entries, url="https://x.example/pl", title="Zdroj"):
    fake[url] = playlist(entries, title=title)
    catalog.add_sources(st.db, [url])
    scan(st, url)


def rows(st):
    return {r["key"]: r for r in st.db.query("select * from catalog_items")}


def states(st):
    return {k: (r["detail_state"], r["state"]) for k, r in rows(st).items()}


# ------------------------------------------------------------ podrobnosti a miniatury
def test_details_are_stored_with_best_thumbnail_and_search_text(st, fake, info):
    make(st, fake, [e("a", "Starý", thumbnail="https://img.example/flat.jpg")])
    asyncio.run(run_until(st, lambda: states(st)["youtube a"][0] == "done"))
    r = rows(st)["youtube a"]
    assert (r["height"], r["size"], r["duration"], r["title"], r["thumb_url"]) == (1080, 150, 120, "Zjištěno", "https://img.example/max.jpg")
    assert r["thumb_file"] == f"{r['id']}.jpg" and (catalog.thumbs_dir(st.data, st.settings) / r["thumb_file"]).read_bytes() == JPEG
    assert catalog.query_items(st.db, q="zjisteno")["total"] == 1
    assert info.ctxs[0].settings["audio_only"] is False and info.ctxs[0].settings["quality"] == "max"   # i při „jen zvuk“ v nastavení


def test_audio_only_setting_does_not_hide_video_details(st):
    st.settings.update({"audio_only": True, "quality": "compat"})
    ctx = cd.detail_ctx(st)
    assert ctx.settings["audio_only"] is False and ctx.settings["quality"] == "max"
    assert st.settings.get("audio_only") is True                       # nastavení aplikace se nezměnilo


def test_best_thumbnails_order_and_download_fallback(tmp_path, images):
    # yt-dlp řadí miniatury vzestupně podle kvality (poslední je nejlepší) a největším často neuvádí rozměry
    inf = {"thumbnails": [{"url": "https://a/s.jpg", "width": 10, "height": 10}, {"url": "https://a/mid.jpg", "width": 100, "height": 50},
                          {"url": "https://a/big.png"}, {"url": ""}], "thumbnail": "https://a/default.jpg"}
    assert cd.best_thumbnails(inf) == ["https://a/big.png", "https://a/mid.jpg", "https://a/s.jpg", "https://a/default.jpg"]   # „thumbnail“ jako záloha
    assert cd.best_thumbnails({"thumbnails": [{"url": "https://a/1.jpg"}, {"url": "https://a/2.jpg"}], "thumbnail": "https://a/2.jpg"}) == \
        ["https://a/2.jpg", "https://a/1.jpg"]                                                                                      # bez duplicit
    assert cd.best_thumbnails({"thumbnail": "https://a/only.jpg"}) == ["https://a/only.jpg"]
    assert cd.best_thumbnails({}) == []
    f = tmp_path / "t"
    assert cd.download_thumb(f, 7, ["https://a/bad1.jpg", "https://a/html.jpg", "https://a/good.png"]) == "7.png"      # špatné a „html“ se přeskočí
    assert (f / "7.png").read_bytes() == PNG and not list(f.glob("*.part"))
    assert cd.download_thumb(f, 7, ["https://a/new.jpg"]) == "7.jpg" and not (f / "7.png").exists()                  # jeden soubor na položku
    assert cd.download_thumb(f, 8, ["https://a/bad1.jpg", "https://a/bad2.jpg"]) is None
    assert len(images) == 6
    many_bad = [f"https://a/bad{i}.jpg" for i in range(cd.THUMB_CANDIDATES)]
    assert cd.download_thumb(f, 9, [*many_bad, "https://a/good.jpg"]) is None            # zkusí se nejvýš THUMB_CANDIDATES kandidátů
    assert cd.download_thumb(f, 10, [*many_bad[:-1], "https://a/good.jpg"]) == "10.jpg"


def test_looks_like_image(tmp_path):
    for data, ok in ((JPEG, True), (PNG, True), (b"GIF89a" + b"x" * 20, True), (b"RIFF\x00\x00\x00\x00WEBPVP8 ", True), (b"<html>", False), (b"", False)):
        p = tmp_path / "x"
        p.write_bytes(data)
        assert cd.looks_like_image(p) is ok
    assert cd.looks_like_image(tmp_path / "neni") is False


def test_late_details_do_not_resurrect_a_removed_item(st, fake, info):
    make(st, fake, [e("a")])
    w = cd.DetailWorker(st)
    item = w.pick()
    with st.db.conn() as c:
        c.execute("update catalog_items set state='removed' where id=?", (item["id"],))
    asyncio.run(w._store(item, info.default))
    r = rows(st)["youtube a"]
    assert r["state"] == "removed" and r["detail_state"] == "pending" and r["height"] is None
    assert not (catalog.thumbs_dir(st.data, st.settings)).exists() or not list(catalog.thumbs_dir(st.data, st.settings).iterdir())


# ------------------------------------------------------------ pořadí práce, pauza
def test_details_wait_for_all_lists_and_respect_pause(st, fake, info):
    make(st, fake, [e("a"), e("b")])
    with st.db.conn() as c:
        c.execute("update catalog_sources set status='scanning'")           # seznam jiného zdroje se ještě zjišťuje
    w = cd.DetailWorker(st)

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(w.run(stop))
        await asyncio.sleep(0.4)
        assert info.calls == [] and w.status()["waiting_for_lists"] is True
        with st.db.conn() as c:
            c.execute("update catalog_sources set status='done'")
        st.db.kv_set("catalog_paused", True)
        await asyncio.sleep(0.4)
        assert info.calls == [] and w.status()["paused"] is True
        st.db.kv_set("catalog_paused", False)
        for _ in range(100):
            await asyncio.sleep(0.05)
            if len(info.calls) == 2:
                break
        stop.set()
        await asyncio.wait_for(t, 3)
    asyncio.run(go())
    assert len(info.calls) == 2 and {v[0] for v in states(st).values()} == {"done"}


def test_only_visible_items_get_details(st, fake, info):
    make(st, fake, [e("a"), e("b"), e("c")])
    with st.db.conn() as c:
        c.execute("update catalog_items set state='removed' where key='youtube b'")
        c.execute("update catalog_items set state='gone' where key='youtube c'")
    asyncio.run(run_until(st, lambda: states(st)["youtube a"][0] == "done"))
    assert states(st)["youtube b"][0] == "pending" and states(st)["youtube c"][0] == "pending"
    assert len(info.calls) == 1


# ------------------------------------------------------------ rozložení po webech
def test_one_request_at_a_time_per_host_with_gap_but_hosts_in_parallel(st, fake, info):
    st.settings.update({"catalog_gap": 1})
    entries = [e(f"a{i}", url=f"https://host-a.example/v/{i}") for i in range(3)] + [e(f"b{i}", url=f"https://host-b.example/v/{i}") for i in range(3)]
    make(st, fake, entries)
    info.delay["s"] = 0.05
    w = cd.DetailWorker(st)
    w.gap = lambda: 0.15                                                       # pevná pauza pro zkoušku
    asyncio.run(run_until(st, lambda: len(info.calls) == 6, worker=w))
    by_host = {}
    for url, t in info.calls:
        by_host.setdefault(url.split("/")[2], []).append(t)
    for host, ts in by_host.items():
        assert len(ts) == 3 and all(b - a >= 0.18 for a, b in zip(ts, ts[1:])), (host, ts)     # 0,05 s práce + 0,15 s pauza (s rezervou)
    assert abs(by_host["host-a.example"][0] - by_host["host-b.example"][0]) < 0.15              # weby jedou souběžně


def test_at_most_three_hosts_at_once(st, fake, info):
    make(st, fake, [e(f"h{i}", url=f"https://host-{i}.example/v/1") for i in range(5)])
    peak, cur = {"n": 0}, {"n": 0}
    orig = cd.ytdlp.full_info

    async def counting(url, ctx, timeout=180):
        cur["n"] += 1
        peak["n"] = max(peak["n"], cur["n"])
        try:
            await asyncio.sleep(0.2)
            return await orig(url, ctx, timeout)
        finally:
            cur["n"] -= 1
    cd.ytdlp.full_info = counting
    try:
        asyncio.run(run_until(st, lambda: {v[0] for v in states(st).values()} == {"done"}, timeout=10))
    finally:
        cd.ytdlp.full_info = orig
    assert peak["n"] == cd.MAX_HOSTS


def test_gap_depends_on_setting_and_performance_mode(st):
    w = cd.DetailWorker(st)
    st.settings.update({"catalog_gap": 0})
    assert w.gap() == 0
    for mode, lo, hi in (("full", 7, 13), ("balanced", 14, 26), ("eco", 28, 52)):
        st.settings.update({"catalog_gap": 10, "perf_mode": mode})
        assert all(lo <= w.gap() <= hi for _ in range(50)), mode


# ------------------------------------------------------------ chyby a odkládání
@pytest.mark.parametrize("kind,msg,item_state", [
    ("removed", "ERROR: Video unavailable", "gone"),
    ("login", "ERROR: Private video. Sign in if you've been granted access", "gone"),
    ("geo", "not available in your country", "new"),
    ("login", "This video is age-restricted", "new"),
    ("other", "boom", "new"),
    ("unsupported", "Unsupported URL", "new"),
])
def test_item_level_errors_fail_only_that_video(st, fake, info, kind, msg, item_state):
    st.settings.update({"catalog_slow_browser": False})                    # s prohlížečem by „unsupported“ čekalo na pomalou vrstvu
    make(st, fake, [e("a"), e("b")])
    info.answers["https://example.com/watch/a"] = ResolveError(msg, kind)
    asyncio.run(run_until(st, lambda: states(st)["youtube b"][0] == "done" and states(st)["youtube a"][0] == "failed"))
    r = rows(st)["youtube a"]
    assert r["state"] == item_state and msg.split(".")[0][:20].lower() in r["detail_error"].lower()
    assert states(st)["youtube b"] == ("done", "new")                      # ostatní videa se zjistí dál


@pytest.mark.parametrize("kind,msg", [("network", "HTTP Error 429: Too Many Requests"), ("login", "Sign in to confirm you're not a bot"),
                                      ("cookies", "could not copy cookies database")])
def test_host_level_errors_back_off_the_host_and_keep_the_video_pending(st, fake, info, monkeypatch, kind, msg):
    monkeypatch.setattr(cd, "BACKOFF_FIRST", 0.3)
    monkeypatch.setattr(cd, "BACKOFF_LOGIN", 0.3)
    make(st, fake, [e("a", url="https://host-a.example/v/1"), e("a2", url="https://host-a.example/v/2"), e("b", url="https://host-b.example/v/1")])
    info.answers["https://host-a.example/v/1"] = ResolveError(msg, kind)

    async def go():
        w = cd.DetailWorker(st)
        stop = asyncio.Event()
        t = asyncio.create_task(w.run(stop))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if states(st)["https://host-b.example/v/1" if False else "youtube b"][0] == "done":
                break
        assert states(st)["youtube a"][0] == "pending" and states(st)["youtube a2"][0] == "pending"    # web A čeká
        b = w.status()["backoff"]
        assert len(b) == 1 and b[0]["host"] == "host-a.example" and b[0]["reason"]
        info.answers.pop("https://host-a.example/v/1")                                             # web se uzdravil
        for _ in range(150):
            await asyncio.sleep(0.05)
            if states(st)["youtube a"][0] == "done" and states(st)["youtube a2"][0] == "done":
                break
        stop.set()
        await asyncio.wait_for(t, 3)
        assert w.status()["backoff"] == []
    asyncio.run(go())
    assert states(st)["youtube a"] == ("done", "new")


def test_backoff_doubles_and_is_capped(st):
    w = cd.DetailWorker(st)
    delays = []
    for _ in range(8):
        w._back_off("h.example", 120.0, "x")
        delays.append(w.backoff["h.example"]["delay"])
    assert delays[:3] == [120.0, 240.0, 480.0] and delays[-1] == cd.BACKOFF_MAX == max(delays)


def test_unexpected_exception_fails_the_video_and_worker_continues(st, fake, info):
    make(st, fake, [e("a"), e("b")])
    info.answers["https://example.com/watch/a"] = RuntimeError("boom")
    asyncio.run(run_until(st, lambda: states(st)["youtube b"][0] == "done"))
    assert states(st)["youtube a"][0] == "failed" and "RuntimeError" in rows(st)["youtube a"]["detail_error"]


def test_worker_stops_promptly_while_requests_are_running(st, fake, info):
    make(st, fake, [e("a")])
    info.delay["s"] = 30

    async def go():
        w = cd.DetailWorker(st)
        stop = asyncio.Event()
        t = asyncio.create_task(w.run(stop))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if info.calls:
                break
        t0 = time.monotonic()
        stop.set()
        await asyncio.wait_for(t, 3)
        return time.monotonic() - t0
    assert asyncio.run(go()) < 2
    assert states(st)["youtube a"][0] == "pending"                              # po restartu se naváže


# ------------------------------------------------------------ miniatury
def test_thumbs_loop_downloads_marks_failures_and_retry_requeues_them(st, fake, info, images):
    make(st, fake, [e("ok", thumbnail=None, thumbnails=[{"url": "https://img.example/ok.jpg"}]),
                    e("bad", thumbnails=[{"url": "https://img.example/bad.jpg"}])])
    st.db.kv_set("catalog_paused", False)
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")             # jen miniatury
    asyncio.run(run_until(st, lambda: all(r["thumb_file"] is not None for r in rows(st).values()), thumbs=True))
    r = rows(st)
    assert r["youtube ok"]["thumb_file"] == f"{r['youtube ok']['id']}.jpg" and r["youtube bad"]["thumb_file"] == ""
    n = len(images)
    asyncio.run(run_until(st, lambda: True, thumbs=True))
    assert len(images) == n                                                    # selhání se nezkouší pořád dokola
    assert {i["has_thumb"] for i in catalog.query_items(st.db)["items"]} == {True, False}
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='failed' where key='youtube bad'")
    res = cd.retry_failed(st.db)
    assert res == {"details": 1, "thumbs": 1}
    r = rows(st)["youtube bad"]
    assert r["thumb_file"] is None and r["detail_state"] == "pending"
    assert cd.retry_failed(st.db, source=99999) == {"details": 0, "thumbs": 0}


def test_paused_worker_downloads_no_thumbnails(st, fake, info, images):
    make(st, fake, [e("a", thumbnails=[{"url": "https://img.example/a.jpg"}])])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")
    st.db.kv_set("catalog_paused", True)

    async def go():
        w = cd.DetailWorker(st)
        stop = asyncio.Event()
        t = asyncio.create_task(w.thumbs_loop(stop))
        await asyncio.sleep(0.5)
        stop.set()
        await asyncio.wait_for(t, 3)
    asyncio.run(go())
    assert images == [] and rows(st)["youtube a"]["thumb_file"] is None


def test_thumbs_dir_default_and_custom_and_delete_source_cleans_files(st, fake, info, tmp_path):
    assert catalog.thumbs_dir(st.data, st.settings) == st.data / "catalog" / "thumbs"
    custom = tmp_path / "moje-miniatury"
    st.settings.update({"catalog_thumbs_dir": str(custom)})
    assert catalog.thumbs_dir(st.data, st.settings) == custom
    make(st, fake, [e("a", thumbnails=[{"url": "https://img.example/a.jpg"}]), e("b", thumbnails=[{"url": "https://img.example/b.jpg"}])])
    asyncio.run(run_until(st, lambda: all(r["thumb_file"] for r in rows(st).values()), thumbs=True))
    files = sorted(p.name for p in custom.iterdir())
    assert len(files) == 2
    (custom / "cizi.txt").write_text("x")
    outside = tmp_path / "mimo.jpg"
    outside.write_bytes(JPEG)
    with st.db.conn() as c:
        c.execute("update catalog_items set thumb_file='../mimo.jpg' where key='youtube b'")   # podvržený název mimo složku
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    assert catalog.delete_source(st.db, sid, custom) is True
    left = {p.name for p in custom.iterdir()}
    assert outside.exists() and "cizi.txt" in left                       # soubor mimo složku ani cizí soubor se nesmaží
    assert len(left) == 2 and len(left & set(files)) == 1                # smazala se miniatura položky s platným názvem, podvržená zůstala


# ------------------------------------------------------------ API
def test_api_overview_pause_retry_and_thumbs(client, fake, info, tmp_path, data):
    c, s = client
    s.db.kv_set("catalog_paused", False)
    fake["https://x.example/pl"] = playlist([e("a", thumbnails=[{"url": "https://img.example/a.jpg"}]), e("b")], title="Zdroj")
    catalog.add_sources(s.db, ["https://x.example/pl"])
    st = St(s.data)
    st.db = s.db
    scan(st, "https://x.example/pl")
    ov = c.get("/api/catalog").json()
    assert ov["details"]["pending"] == 2 and ov["details"]["paused"] is False and ov["details"]["waiting_for_lists"] is False
    assert c.post("/api/catalog/pause", json={"paused": True}).json()["details"]["paused"] is True
    assert c.post("/api/catalog/pause", json={"paused": "ano"}).status_code == 400
    assert c.post("/api/catalog/pause", json=[1]).status_code == 400
    assert c.post("/api/catalog/pause", json={"paused": False}).json()["details"]["paused"] is False
    # miniatura: žádná → 404; po stažení se předá i s hlavičkou mezipaměti; podvržený název → 404
    item = c.get("/api/catalog/items").json()["items"][0]
    assert item["thumb"] is None and c.get(f"/api/catalog/thumb/{item['id']}").status_code == 404
    folder = catalog.thumbs_dir(s.data, s.settings)
    folder.mkdir(parents=True)
    (folder / f"{item['id']}.jpg").write_bytes(JPEG)
    with s.db.conn() as cc:
        cc.execute("update catalog_items set thumb_file=? where id=?", (f"{item['id']}.jpg", item["id"]))
    item = c.get("/api/catalog/items").json()["items"][0]
    assert item["thumb"].startswith(f"/api/catalog/thumb/{item['id']}")
    r = c.get(item["thumb"])
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg" and "max-age" in r.headers["cache-control"]
    with s.db.conn() as cc:
        cc.execute("update catalog_items set thumb_file='../../etc/passwd' where id=?", (item["id"],))
    assert c.get(f"/api/catalog/thumb/{item['id']}").status_code == 404
    assert c.get("/api/catalog/thumb/99999999999999999999999").status_code == 404
    # opakování
    with s.db.conn() as cc:
        cc.execute("update catalog_items set detail_state='failed'")
    assert c.post("/api/catalog/retry", json={}).json()["details"] == 2
    assert c.post("/api/catalog/retry", json={"source": "x"}).status_code == 400
    assert c.post("/api/catalog/retry").status_code == 200
    # smazání zdroje smaže i miniatury
    (folder / "1.jpg").write_bytes(JPEG)
    sid = c.get("/api/catalog").json()["sources"][0]["id"]
    with s.db.conn() as cc:
        cc.execute("update catalog_items set thumb_file=?||'.jpg' where id=?", (str(item["id"]), item["id"]))
    (folder / f"{item['id']}.jpg").write_bytes(JPEG)
    assert c.delete(f"/api/catalog/sources/{sid}").status_code == 200
    assert not (folder / f"{item['id']}.jpg").exists()


def test_api_settings_for_catalog(client, tmp_path):
    c, s = client
    assert c.put("/api/settings", json={"catalog_gap": 61}).status_code == 400
    assert c.put("/api/settings", json={"catalog_gap": -1}).status_code == 400
    assert c.put("/api/settings", json={"catalog_gap": 0}).status_code == 200
    f = tmp_path / "soubor"
    f.write_text("x")
    assert c.put("/api/settings", json={"catalog_thumbs_dir": str(f / "pod")}).status_code == 400
    ok = tmp_path / "miniatury"
    assert c.put("/api/settings", json={"catalog_thumbs_dir": str(ok)}).status_code == 200 and ok.is_dir()
    assert c.put("/api/settings", json={"catalog_thumbs_dir": ""}).status_code == 200
    assert c.get("/api/settings").json()["values"]["catalog_slow_browser"] is True


def test_thumbnail_falls_back_to_alternatives_stored_with_the_item(st, fake, info, images):
    # nejlepší (poslední) varianta neexistuje, horší ano: u starých videí chybí největší miniatury
    make(st, fake, [e("a", thumbnails=[{"url": "https://img.example/ok.jpg"}, {"url": "https://img.example/bad.jpg"}])])
    r = rows(st)["youtube a"]
    assert r["thumb_url"] == "https://img.example/bad.jpg" and r["thumb_alts"] == '["https://img.example/ok.jpg"]'
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")
    asyncio.run(run_until(st, lambda: rows(st)["youtube a"]["thumb_file"] is not None, thumbs=True))
    assert rows(st)["youtube a"]["thumb_file"].endswith(".jpg") and images == ["https://img.example/bad.jpg", "https://img.example/ok.jpg"]


def test_details_store_alternatives_for_the_thumbnails_loop(st, fake, info):
    make(st, fake, [e("a")])
    asyncio.run(run_until(st, lambda: states(st)["youtube a"][0] == "done"))
    r = rows(st)["youtube a"]
    assert r["thumb_url"] == "https://img.example/max.jpg" and r["thumb_alts"] == '["https://img.example/small.jpg"]'
