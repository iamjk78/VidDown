"""Odběry: kontrola nových videí, datum „od“, archiv, potvrzení první dávky, vlastní složka, API (bez sítě)."""
import asyncio
import datetime as dt
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from viddown import runner as runner_mod
from viddown import subscriptions as subs
from viddown.config import Secrets, Settings
from viddown.db import DB
from viddown.resolvers import ResolveError
from viddown.server import create_app


class FakeEngines:
    busy = None
    engines = {}

    class E:
        def bin_path(self, *a, **k):
            return None

    def get(self, name):
        return self.E()

    def status(self):
        return []

    @staticmethod
    def chromium_status():
        return {"installed": True, "playwright": "x"}

    def update_all(self):
        return {}


@pytest.fixture()
def rt(data, tmp_path):
    s = Settings()
    s.update({"download_dir": str(tmp_path / "dl"), "sleep_min": 0, "sleep_max": 0, "concurrency": 1,
              "engine_auto_update": False, "min_free_gb": 0, "playlist_confirm_threshold": 3})
    return runner_mod.Runner(DB(data / "t.db"), s, FakeEngines(), data)


def entry(vid, date, **kw):
    return {"id": vid, "url": f"https://example.com/watch/{vid}", "title": f"Video {vid}", "upload_date": date.replace("-", ""),
            "duration": 60, "channel": "Kanál", **kw}


def fake_probe(entries_by_url):
    async def probe(url, ctx, timeout=300, playlist_end=None):
        return {"entries": entries_by_url[url]}
    return probe


def add_sub(rt, tmp_path, since="2026-10-15", kind="channel", **kw):
    return rt.db.sub_add("https://example.com/c", str(tmp_path / "odber"), kind=kind, title="Kanál", since=since, **kw)


def run(coro):
    return asyncio.run(coro)


def test_parse_since():
    today = dt.date.today()
    assert subs.parse_since(None) is None and subs.parse_since("all") is None and subs.parse_since("") is None
    assert subs.parse_since("now") == today.isoformat()
    assert subs.parse_since("2026-03-05") == "2026-03-05"
    month = dt.date.fromisoformat(subs.parse_since("month"))
    assert 27 <= (today - month).days <= 31
    with pytest.raises(ValueError):
        subs.parse_since("včera")


def test_queues_only_videos_since_date_and_stops_at_first_old(rt, tmp_path, monkeypatch):
    sid = add_sub(rt, tmp_path)
    es = [entry("a", "2026-11-09"), entry("b", "2026-11-01"), entry("c", "2026-10-01"), entry("d", "2026-09-01")]
    monkeypatch.setattr(subs.ytdlp, "probe", fake_probe({"https://example.com/c": es}))
    r = run(subs.check(rt, sid))
    assert r == {"queued": 2, "pending": 0}
    jobs = rt.db.query("select * from jobs order by id")
    assert [j["url"] for j in jobs] == ["https://example.com/watch/a", "https://example.com/watch/b"]
    j = jobs[0]
    assert j["source"] == "subscription" and j["sub_id"] == sid and j["status"] == "queued"
    assert j["target_dir"] == str(tmp_path / "odber") and j["title"] == "Video a"
    sub = rt.db.sub_get(sid)
    assert sub["last_check"] and sub["last_error"] is None
    assert json.loads(sub["seen_old"]) == ["c"]          # d se nevyhodnocovalo: kanál je od nejnovějších
    # druhá kontrola: nic nového; nové video se přidá
    assert run(subs.check(rt, sid))["queued"] == 0
    es.insert(0, entry("e", "2026-11-10"))
    assert run(subs.check(rt, sid))["queued"] == 1
    assert rt.db.query("select url from jobs where sub_id=? order by id desc limit 1", (sid,))[0]["url"].endswith("/e")


def test_archive_and_live_are_skipped(rt, tmp_path, monkeypatch):
    sid = add_sub(rt, tmp_path, since=None)
    (rt.data / "archive.txt").write_text("generic a\n")
    es = [entry("a", "2026-11-09"), entry("live", "2026-11-09", live_status="is_live"), entry("ok", "2026-11-08")]
    monkeypatch.setattr(subs.ytdlp, "probe", fake_probe({"https://example.com/c": es}))
    assert run(subs.check(rt, sid))["queued"] == 1
    assert rt.db.query("select url from jobs")[0]["url"].endswith("/ok")


def test_undated_entries_get_date_from_full_info(rt, tmp_path, monkeypatch):
    sid = add_sub(rt, tmp_path)
    es = [{"id": "x", "url": "https://example.com/watch/x", "title": None, "upload_date": None},
          {"id": "y", "url": "https://example.com/watch/y", "title": None, "upload_date": None}]
    monkeypatch.setattr(subs.ytdlp, "probe", fake_probe({"https://example.com/c": es}))
    dates = {"x": "20261105", "y": "20260101"}

    async def full(url, ctx, timeout=120):
        v = url.rsplit("/", 1)[1]
        return {"title": f"Title {v}", "upload_date": dates[v], "thumbnail": "t.jpg", "duration": 10, "channel": "K"}
    monkeypatch.setattr(subs.ytdlp, "full_info", full)
    assert run(subs.check(rt, sid))["queued"] == 1
    j = rt.db.query("select * from jobs")[0]
    assert j["url"].endswith("/x") and j["title"] == "Title x" and j["thumb_url"] == "t.jpg"


def test_playlist_walks_all_entries_not_stopping_at_old(rt, tmp_path, monkeypatch):
    sid = add_sub(rt, tmp_path, kind="playlist")
    es = [entry("a", "2026-11-09"), entry("old", "2026-01-01"), entry("b", "2026-11-02")]   # pořadí playlistu není podle data
    monkeypatch.setattr(subs.ytdlp, "probe", fake_probe({"https://example.com/c": es}))
    assert run(subs.check(rt, sid))["queued"] == 2


def test_first_run_above_threshold_waits_for_confirmation(rt, tmp_path, monkeypatch):
    sid = add_sub(rt, tmp_path, since=None)
    es = [entry(f"v{i}", "2026-11-0%d" % (i + 1)) for i in range(5)]   # práh v testu = 3
    monkeypatch.setattr(subs.ytdlp, "probe", fake_probe({"https://example.com/c": es}))
    assert run(subs.check(rt, sid)) == {"queued": 0, "pending": 5}
    assert rt.db.query("select count(*) n from jobs")[0]["n"] == 0
    assert subs.due(rt.db, 0.0001, time.time() + 3600) is None            # čekající odběr se nekontroluje
    assert subs.confirm_pending(rt.db, sid) == 5
    assert rt.db.query("select count(*) n from jobs where sub_id=?", (sid,))[0]["n"] == 5
    assert rt.db.sub_get(sid)["pending"] is None
    # zamítnutí: videa se příště nenabídnou
    sid2 = rt.db.sub_add("https://example.com/c2", str(tmp_path / "o2"), kind="channel", since=None)
    monkeypatch.setattr(subs.ytdlp, "probe", fake_probe({"https://example.com/c2": es}))
    assert run(subs.check(rt, sid2))["pending"] == 5
    assert subs.reject_pending(rt.db, sid2) == 5
    assert run(subs.check(rt, sid2)) == {"queued": 0, "pending": 0}       # zamítnutá videa drží seen_old
    assert rt.db.query("select count(*) n from jobs where sub_id=?", (sid2,))[0]["n"] == 0


def test_check_error_is_stored_and_does_not_raise(rt, tmp_path, monkeypatch):
    sid = add_sub(rt, tmp_path)

    async def boom(url, ctx, timeout=300, playlist_end=None):
        raise ResolveError("Kanál neexistuje", "removed")
    monkeypatch.setattr(subs.ytdlp, "probe", boom)
    assert run(subs.check(rt, sid))["error"] == "Kanál neexistuje"
    assert rt.db.sub_get(sid)["last_error"] == "Kanál neexistuje"


def test_due_respects_interval_enabled_and_order(rt, tmp_path):
    now = time.time()
    a = rt.db.sub_add("https://x/a", "/tmp/a", last_check=now - 7 * 3600)
    b = rt.db.sub_add("https://x/b", "/tmp/b", last_check=now - 9 * 3600)
    c = rt.db.sub_add("https://x/c", "/tmp/c", last_check=now - 1 * 3600)
    d = rt.db.sub_add("https://x/d", "/tmp/d", last_check=None, enabled=0)
    assert subs.due(rt.db, 6, now)["id"] == b          # nejdéle nekontrolovaný
    rt.db.sub_update(b, last_check=now)
    assert subs.due(rt.db, 6, now)["id"] == a
    rt.db.sub_update(a, last_check=now)
    assert subs.due(rt.db, 6, now) is None             # c je čerstvý, d vypnutý


def test_subscription_job_is_saved_to_its_own_folder_with_channel_template(rt, tmp_path, monkeypatch):
    from tests.test_runner import fake_download, run_until
    sid = add_sub(rt, tmp_path, since=None)
    rt.settings.update({"channel_name_template": "{kanál}_{název}"})
    monkeypatch.setattr(subs.ytdlp, "probe", fake_probe({"https://example.com/c": [entry("a", "2026-11-09")]}))
    run(subs.check(rt, sid))
    jid = rt.db.query("select id from jobs")[0]["id"]
    rt.db.update(jid, info={"full": True, "requested_formats": [{"format_id": "1"}], "title": "Video a", "channel": "Kanál"})
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: {}))
    asyncio.run(run_until(rt, lambda: rt.db.get(jid)["status"] == "done"))
    j = rt.db.get(jid)
    assert j["status"] == "done"
    p = Path(j["filepath"])
    assert p.parent == tmp_path / "odber" and p.name == "Kanál_Video a.mp4"
    assert p.with_suffix(".jpg").exists()


# ------------------------------------------------------------ API
class State:
    def __init__(self, rt, data):
        self.data = data
        self.settings = rt.settings
        self.secrets = Secrets()
        self.db = rt.db
        self.engines = rt.engines
        self.runner = rt


@pytest.fixture()
def client(rt, data, monkeypatch):
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    return TestClient(create_app(State(rt, data))), rt


def test_api_create_validates_and_lists(client, tmp_path, monkeypatch):
    c, rt = client
    from viddown import server

    async def pv(url, ctx):
        if "video" in url:
            return {"type": "video", "title": "V"}
        return {"type": "channel", "title": "Můj kanál", "thumb_url": "t.jpg", "count": 3}
    monkeypatch.setattr(server, "probe_url", pv)
    r = c.post("/api/subscriptions", json={"url": "https://example.com/video/1", "folder": str(tmp_path / "x")})
    assert r.status_code == 400 and "jedno video" in r.json()["detail"]
    assert c.post("/api/subscriptions", json={"url": "bez url"}).status_code == 400
    r = c.post("/api/subscriptions", json={"url": "https://example.com/@kanal", "folder": "relativni/cesta"})
    assert r.status_code == 400                                  # jen absolutní cesta
    r = c.post("/api/subscriptions", json={"url": "https://example.com/@kanal", "folder": str(tmp_path / "ulozeni"), "since": "včera"})
    assert r.status_code == 400
    r = c.post("/api/subscriptions", json={"url": "https://example.com/@kanal", "folder": str(tmp_path / "ulozeni"), "since": "2026-11-01"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["title"] == "Můj kanál" and s["kind"] == "channel" and s["since"] == "2026-11-01" and s["enabled"] == 1
    assert (tmp_path / "ulozeni").is_dir()
    assert c.post("/api/subscriptions", json={"url": "https://example.com/@kanal", "folder": str(tmp_path / "ulozeni")}).status_code == 409
    # výchozí složka = cílová složka / název a výchozí „od“ = dnes
    r2 = c.post("/api/subscriptions", json={"url": "https://example.com/@jiny"}).json()
    assert r2["folder"].endswith("Můj kanál") and r2["since"] == dt.date.today().isoformat()
    items = c.get("/api/subscriptions").json()["items"]
    assert len(items) == 2 and items[0]["queued"] == 0


def test_api_update_check_and_delete(client, tmp_path):
    c, rt = client
    sid = rt.db.sub_add("https://example.com/c", str(tmp_path / "a"), kind="channel", title="K", since="2026-11-01")
    j = rt.db.add("https://example.com/v1", status="queued", sub_id=sid, target_dir=str(tmp_path / "a"))
    d = rt.db.add("https://example.com/v2", status="done", sub_id=sid, finished_at=1.0)
    r = c.put(f"/api/subscriptions/{sid}", json={"folder": str(tmp_path / "b"), "enabled": False, "since": None})
    assert r.status_code == 200 and r.json()["enabled"] == 0 and r.json()["since"] is None
    assert rt.db.get(j)["target_dir"] == str(tmp_path / "b")        # čekající úlohy dostanou novou složku
    rt.db.sub_update(sid, seen_old=["x"])
    c.put(f"/api/subscriptions/{sid}", json={"since": "2026-01-01"})
    assert rt.db.sub_get(sid)["seen_old"] is None                   # změna data zneplatní „starší videa“
    assert c.put(f"/api/subscriptions/{sid}", json={"folder": "x"}).status_code == 400
    assert c.get("/api/subscriptions/999").status_code == 404
    # smazání se zachováním historie
    assert c.delete(f"/api/subscriptions/{sid}").status_code == 200
    assert rt.db.get(j)["status"] == "cancelled" and rt.db.get(d)["sub_id"] is None and rt.db.get(d)["status"] == "done"
    # smazání i s historií
    sid2 = rt.db.sub_add("https://example.com/c2", str(tmp_path / "c"), kind="playlist")
    d2 = rt.db.add("https://example.com/v3", status="done", sub_id=sid2, finished_at=1.0)
    assert c.delete(f"/api/subscriptions/{sid2}?keep_history=false").status_code == 200
    assert rt.db.get(d2) is None


def _hist_job(rt, sid, url):
    jid = rt.db.add(url, source="subscription", sub_id=sid)
    rt.db.update(jid, status="done", finished_at=time.time())
    return jid


def test_dual_history_hide_here_then_delete_when_hidden_everywhere(rt, tmp_path):
    sid = add_sub(rt, tmp_path)
    a, b = _hist_job(rt, sid, "https://x/a"), _hist_job(rt, sid, "https://x/b")
    plain = rt.db.add("https://x/p")
    rt.db.update(plain, status="done", finished_at=time.time())
    # odstranění z celkové historie: záznam odběru zůstane v historii odběru, běžný záznam zmizí úplně
    assert rt.db.delete_history([a, plain], view=0, scope="here") == 2
    assert rt.db.get(plain) is None and rt.db.get(a)["hide_global"] == 1
    assert {j["id"] for j in rt.db.history()} == {b}
    assert {j["id"] for j in rt.db.history(sub=sid)} == {a, b}
    # skrytí ještě v historii odběru → nikde není vidět, smaže se fyzicky
    rt.db.delete_history([a], view=sid, scope="here")
    assert rt.db.get(a) is None
    # druhá cesta: nejdřív z odběru, pak z celkové
    rt.db.delete_history([b], view=sid, scope="here")
    assert rt.db.get(b)["hide_sub"] == 1 and rt.db.history(sub=sid) == [] and len(rt.db.history()) == 1
    rt.db.delete_history([b], view=0, scope="here")
    assert rt.db.get(b) is None


def test_dual_history_scope_both_and_filter_and_sub_delete(rt, tmp_path):
    sid = add_sub(rt, tmp_path)
    a, b, c = (_hist_job(rt, sid, f"https://x/{i}") for i in "abc")
    assert rt.db.delete_history([a], view=sid, scope="both") == 1 and rt.db.get(a) is None
    assert rt.db.delete_history_matching(sub=sid, scope="here") == 2
    assert rt.db.history(sub=sid) == [] and len(rt.db.history()) == 2
    # smazání odběru se zachováním historie: co je skryté v celkové historii, se nesmí vrátit
    rt.db.delete_history([b], view=0, scope="here")
    rt.db.sub_delete(sid, keep_history=True)
    assert [j["id"] for j in rt.db.history()] == [c] and rt.db.get(c)["hide_sub"] == 0


def test_api_history_scope(client, tmp_path):
    c, rt = client
    sid = add_sub(rt, tmp_path)
    a = _hist_job(rt, sid, "https://x/a")
    assert c.request("DELETE", "/api/history", json={"ids": [a], "view": 0}).json()["deleted"] == 1
    assert c.get("/api/history").json()["matched"] == 0
    assert c.get(f"/api/history?sub={sid}").json()["matched"] == 1
    assert c.request("DELETE", "/api/history", json={"filter": {"sub": sid}, "scope": "both"}).json()["deleted"] == 1
    assert rt.db.get(a) is None


def test_stats_recorded_independent_of_history_and_reset(client, tmp_path):
    c, rt = client
    sid = add_sub(rt, tmp_path)
    now = time.time()
    for i, (ok, size) in enumerate([(True, 100), (True, 300), (False, 0)]):
        jid = rt.db.add(f"https://www.youtube.com/watch?v={i}", source="subscription", sub_id=sid, channel="Kanal A")
        rt.db.update(jid, status="done" if ok else "failed", filesize=size, started_at=now - 20, finished_at=now - 10, method="yt-dlp")
        rt.db.record_download(rt.db.get(jid), ok)
    rt.db.delete_history_matching(scope="both")
    rt.db.delete_history_matching(sub=sid, scope="both")
    r = c.get("/api/stats", params={"t0": now - 86400, "tz": 120}).json()
    assert (r["done"], r["failed"], r["bytes"]) == (2, 1, 400)
    assert r["channels"][0]["name"] == "Kanal A" and r["channels"][0]["n"] == 2
    assert r["sites"][0]["name"] == "youtube.com" and r["sources"][0]["name"] == "subscription"
    assert sum(x["n"] for x in r["series"]) == 2 and r["fmt"] == "%Y-%m-%d %H:00"
    assert c.get("/api/stats", params={"t0": now - 86400, "sub": sid + 5}).json()["done"] == 0
    assert c.get("/api/stats").json()["done"] == 2   # celé období
    assert c.delete("/api/stats").json()["deleted"] == 3
    assert c.get("/api/stats").json()["done"] == 0


def test_migration_backfills_downloads(data):
    import sqlite3
    from viddown import db as dbm
    path = data / "old.db"
    con = sqlite3.connect(path)
    con.executescript(dbm.SCHEMA)
    con.execute("pragma user_version=3")
    for v, sql in ((2, dbm.SUBSCRIPTIONS_V2), (3, dbm.HISTORY_FLAGS_V3)):
        for st in dbm._split_sql(sql):
            con.execute(st)
    con.execute("insert into jobs(url,status,filesize,pos,created_at,updated_at,finished_at,started_at,channel) "
                "values('https://www.vimeo.com/1','done',500,1,1,1,100,90,'C')")
    con.execute("insert into jobs(url,status,pos,created_at,updated_at,finished_at) values('https://x.cz/2','failed',2,1,1,110)")
    con.commit(); con.close()
    d = DB(path)
    assert d.schema_version == dbm.MIGRATIONS[-1][0]
    rows = d.query("select * from downloads order by ts")
    assert [(r["ok"], r["bytes"], r["site"]) for r in rows] == [(1, 500, "vimeo.com"), (0, 0, "x.cz")]


def test_expand_skips_videos_already_queued_and_duplicate_playlist_is_refused(rt):
    entries = lambda: [{"url": f"https://x/v{i}", "title": f"V{i}"} for i in range(3)]  # noqa: E731
    p1, new1 = rt.add("https://x/list")
    assert new1
    rt._expand(rt.db.get(p1), entries())
    assert len(rt.db.children(p1)) == 3
    # stejná adresa playlistu, jehož videa čekají, se znovu nepřidá
    p2, new2 = rt.add("https://x/list")
    assert (p2, new2) == (p1, False)
    # jiný playlist s týmiž videi nepřidá nic navíc
    other = rt.db.add("https://x/other", status="probing", kind="playlist")
    rt._expand(rt.db.get(other), entries() + [{"url": "https://x/v9", "title": "N"}])
    assert [c["url"] for c in rt.db.children(other)] == ["https://x/v9"]


def test_cpu_modes_and_api(client):
    from viddown import cpu
    c, rt = client
    assert cpu.MODES["eco"][2] == 1
    assert rt.eff_concurrency({"concurrency": 4, "perf_mode": "eco"}) == 1
    assert rt.eff_concurrency({"concurrency": 4, "perf_mode": "balanced"}) == 4
    assert rt.eff_concurrency({"concurrency": 4}) == 4
    rt.cpu.sample("balanced"); rt.cpu._last_t -= 3; rt.cpu.sample("balanced")
    r = c.get("/api/cpu").json()
    assert r["mode"] == "balanced" and "history" in r and r["cores"] > 0
    assert c.put("/api/settings", json={"perf_mode": "eco"}).status_code == 200
    assert c.put("/api/settings", json={"perf_mode": "nope"}).status_code in (400, 422)
    assert c.post("/api/restart").status_code == 501   # v testu není hlavní smyčka
    cpu._nice = 0


def test_static_files_are_revalidated(client):
    c, _ = client
    r = c.get("/static/app.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_index_links_are_versioned(client):
    c, _ = client
    html = c.get("/").text
    assert "/static/app.js?v=" in html and "/static/app.css?v=" in html


def test_phases_recorded_and_stats_expose_them(client):
    c, rt = client
    now = time.time()
    jid = rt.db.add("https://www.youtube.com/watch?v=p", source="gui")
    rt.db.update(jid, status="done", filesize=10, started_at=now - 30, finished_at=now)
    rt.db.record_download(rt.db.get(jid), True, {"dl": 10.0, "post": 15.0, "move": 5.0})
    r = c.get("/api/stats", params={"t0": now - 3600}).json()
    assert r["phases"]["n"] == 1 and (r["phases"]["dl"], r["phases"]["post"], r["phases"]["move"]) == (10.0, 15.0, 5.0)
    rt.db.update(jid, stage="post")
    assert rt.db.get(jid)["stage"] == "post"
    assert "temp_used" in rt.disk_status()
    assert set(c.get("/api/cpu").json()["rate_history"]) == {"net_in", "net_out", "io_w", "io_r"}
