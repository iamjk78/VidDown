"""Katalog, etapa 4: stahování z katalogu (složka podle zdroje, „staženo dříve“, srovnání stavu po stažení)."""
import asyncio
import json
from pathlib import Path

import pytest

from tests.test_catalog import e, fake, playlist, rt as _unused, scan  # noqa: F401
from tests.test_runner import fake_download, probe_video, rt, run_until  # noqa: F401
from viddown import catalog
from viddown import runner as runner_mod
from viddown.config import Settings


class St:
    """Co potřebuje scan_one a reconcile: data, nastavení, databázi a runner z testovací fronty."""
    def __init__(self, rt):
        self.data, self.settings, self.db, self.runner = rt.data, rt.settings, rt.db, rt


@pytest.fixture
def st(rt):
    return St(rt)


def load(st, fake, entries, url="https://x.example/pl", title="Můj playlist"):
    fake[url] = playlist(entries, title=title)
    catalog.add_sources(st.db, [url])
    scan(st, url)


def item(st, key):
    return st.db.query("select * from catalog_items where key=?", (key,))[0]


def jobs(st):
    return st.db.query("select * from jobs order by id")


# ------------------------------------------------------------ zařazení do fronty
def test_queue_items_creates_jobs_in_the_source_folder_and_links_them(st, fake):
    load(st, fake, [e("a"), e("b")])
    ids = [item(st, "youtube a")["id"], item(st, "youtube b")["id"]]
    res = catalog.queue_items(st.db, st.runner, ids)
    assert res == {"queued": 2, "linked": 0, "skipped_downloaded": 0, "skipped_state": 0}
    js = jobs(st)
    assert [(j["url"], j["source"], j["subdir"], j["auto_confirm"], j["status"]) for j in js] == \
        [("https://example.com/watch/a", "catalog", "Můj playlist", 1, "new"), ("https://example.com/watch/b", "catalog", "Můj playlist", 1, "new")]
    for it, j in zip(ids, js):
        row = st.db.query("select state, job_id from catalog_items where id=?", (it,))[0]
        assert (row["state"], row["job_id"]) == ("queued", j["id"]) and j["catalog_item_id"] == it


def test_single_video_goes_to_the_download_folder_without_a_subfolder(st, fake, monkeypatch):
    monkeypatch.setattr(catalog.ytdlp, "best_height", lambda i: 720)
    monkeypatch.setattr(catalog.ytdlp, "size_estimate", lambda i: 1000)
    fake["https://v.example/one"] = {"id": "q1", "extractor_key": "Fiktivni", "title": "Jedno", "webpage_url": "https://v.example/one"}
    catalog.add_sources(st.db, ["https://v.example/one"])
    scan(st, "https://v.example/one")
    catalog.queue_items(st.db, st.runner, [item(st, "fiktivni q1")["id"]])
    assert jobs(st)[0]["subdir"] is None


def test_playlist_folder_setting_does_not_matter(st, fake):
    st.settings.update({"playlist_folder": False, "channel_folder": False})
    load(st, fake, [e("a")], title="Jiný seznam")
    catalog.queue_items(st.db, st.runner, [item(st, "youtube a")["id"]])
    assert jobs(st)[0]["subdir"] == "Jiný seznam"


def test_only_new_items_are_queued_and_others_are_counted_as_skipped(st, fake):
    load(st, fake, [e("a"), e("b"), e("c"), e("d")])
    with st.db.conn() as c:
        c.execute("update catalog_items set state='removed' where key='youtube b'")
        c.execute("update catalog_items set state='queued', job_id=99 where key='youtube c'")
        c.execute("update catalog_items set state='gone' where key='youtube d'")
    ids = [item(st, k)["id"] for k in ("youtube a", "youtube b", "youtube c", "youtube d")] + [99999]
    res = catalog.queue_items(st.db, st.runner, ids)
    assert res == {"queued": 1, "linked": 0, "skipped_downloaded": 0, "skipped_state": 4}
    assert len(jobs(st)) == 1


def test_already_queued_url_is_only_linked(st, fake):
    load(st, fake, [e("a")])
    existing, _ = st.runner.add("https://example.com/watch/a")                      # stejné video už ve frontě (ručně)
    a = item(st, "youtube a")["id"]
    res = catalog.queue_items(st.db, st.runner, [a])
    assert res["linked"] == 1 and res["queued"] == 0 and len(jobs(st)) == 1
    row = st.db.query("select state, job_id from catalog_items where id=?", (a,))[0]
    assert (row["state"], row["job_id"]) == ("queued", existing)


def test_downloaded_before_is_skipped_unless_forced_and_forced_ones_leave_the_archive(st, fake, data):
    (data / "archive.txt").write_text("youtube a\nyoutube z\n", "utf-8")
    load(st, fake, [e("a"), e("b")])
    a, b = item(st, "youtube a"), item(st, "youtube b")
    assert a["downloaded_before"] == 1 and b["downloaded_before"] == 0
    res = catalog.queue_items(st.db, st.runner, [a["id"], b["id"]])
    assert res["queued"] == 1 and res["skipped_downloaded"] == 1
    assert (data / "archive.txt").read_text() == "youtube a\nyoutube z\n"            # beze změny
    res = catalog.queue_items(st.db, st.runner, [a["id"]], force=True)
    assert res["queued"] == 1 and res["skipped_downloaded"] == 0
    assert (data / "archive.txt").read_text() == "youtube z\n"                        # jen vynucené video se vyřadilo
    assert [j["url"] for j in jobs(st)] == ["https://example.com/watch/b", "https://example.com/watch/a"]


def test_empty_selection_changes_nothing(st):
    assert catalog.queue_items(st.db, st.runner, []) == {"queued": 0, "linked": 0, "skipped_downloaded": 0, "skipped_state": 0}
    assert jobs(st) == []


# ------------------------------------------------------------ srovnání po stažení
def queued(st, fake, status, error=None, n=1):
    load(st, fake, [e("a", thumbnails=[{"url": "https://img/a.jpg"}])])
    a = item(st, "youtube a")["id"]
    catalog.queue_items(st.db, st.runner, [a])
    j = jobs(st)[0]["id"]
    st.db.update(j, status=status, error=error)
    return a, j


def test_expanded_job_is_decided_by_its_children(st, fake):
    a, j = queued(st, fake, "expanded")
    assert catalog.reconcile(st.db) == {"done": 0, "back": 1}                         # rozbalilo se na nic: nezůstane viset
    assert "bez videí" in catalog.query_items(st.db)["items"][0]["download_error"]
    catalog.queue_items(st.db, st.runner, [a])
    j2 = jobs(st)[-1]["id"]
    st.db.update(j2, status="expanded")
    kids = [st.db.add(f"https://example.com/k{i}", parent_id=j2) for i in range(2)]
    st.db.update(kids[0], status="running")
    st.db.update(kids[1], status="done")
    assert catalog.reconcile(st.db) == {"done": 0, "back": 0}                         # potomek ještě běží
    st.db.update(kids[0], status="done")
    assert catalog.reconcile(st.db) == {"done": 1, "back": 0}


def test_expanded_job_with_only_failed_children_returns_the_item(st, fake):
    a, j = queued(st, fake, "expanded")
    k = st.db.add("https://example.com/k", parent_id=j)
    st.db.update(k, status="failed")
    assert catalog.reconcile(st.db) == {"done": 0, "back": 1}
    assert "nestáhlo" in catalog.query_items(st.db)["items"][0]["download_error"]


def test_force_forgets_url_keyed_items_through_their_last_job(st, fake, data, monkeypatch):
    (data / "archive.txt").write_text("generic abc123\nyoutube z\n", "utf-8")
    load(st, fake, [{"id": None, "url": "https://web.example/dily/1", "title": "Díl", "ie_key": None}])
    it = st.db.query("select * from catalog_items")[0]
    assert it["key"].startswith("http")
    with st.db.conn() as c:
        c.execute("update catalog_items set downloaded_before=1 where id=?", (it["id"],))
    old = st.db.add("https://web.example/dily/1")
    st.db.update(old, status="done", info=json.dumps({"id": "abc123", "extractor_key": "Generic"}))
    catalog.queue_items(st.db, st.runner, [it["id"]], force=True)
    assert (data / "archive.txt").read_text() == "youtube z\n"


@pytest.mark.parametrize("status", ["new", "probing", "queued", "running", "cancelling"])
def test_active_jobs_keep_the_item_queued(st, fake, status):
    a, j = queued(st, fake, status)
    assert catalog.reconcile(st.db) == {"done": 0, "back": 0}
    assert st.db.query("select state from catalog_items where id=?", (a,))[0]["state"] == "queued"


def test_finished_download_removes_the_item_and_its_thumbnail(st, fake, tmp_path):
    a, j = queued(st, fake, "done")
    folder = tmp_path / "t"
    folder.mkdir()
    (folder / f"{a}.jpg").write_bytes(b"x")
    with st.db.conn() as c:
        c.execute("update catalog_items set thumb_file=? where id=?", (f"{a}.jpg", a))
    assert catalog.reconcile(st.db, folder) == {"done": 1, "back": 0}
    row = st.db.query("select * from catalog_items where id=?", (a,))[0]
    assert row["state"] == "done" and row["thumb_file"] is None and row["job_id"] == j and not list(folder.iterdir())
    assert catalog.query_items(st.db)["total"] == 0
    assert catalog.reconcile(st.db, folder) == {"done": 0, "back": 0}                # podruhé nic


@pytest.mark.parametrize("status,error,expected", [("failed", "HTTP Error 403", "stahování selhalo: HTTP Error 403"), ("cancelled", None, "stahování bylo zrušeno"),
                                                   ("skipped", "Již staženo dříve (archiv)", "stahování přeskočeno: Již staženo dříve (archiv)")])
def test_failed_cancelled_or_skipped_download_returns_the_item_with_a_note(st, fake, status, error, expected):
    a, j = queued(st, fake, status, error)
    assert catalog.reconcile(st.db) == {"done": 0, "back": 1}
    row = st.db.query("select state, job_id, detail_error from catalog_items where id=?", (a,))[0]
    assert (row["state"], row["job_id"], row["detail_error"]) == ("new", None, expected)
    out = catalog.query_items(st.db)["items"][0]
    assert out["download_error"] == expected and out["state"] == "new"
    assert out["downloaded_before"] is (status == "skipped")                          # přeskočeno kvůli archivu: příště nabídnout „znovu“
    catalog.queue_items(st.db, st.runner, [a], force=(status == "skipped"))          # po novém zařazení poznámka zmizí
    assert catalog.query_items(st.db)["items"][0]["download_error"] is None


def test_job_removed_from_history_returns_the_item(st, fake):
    a, j = queued(st, fake, "failed")
    with st.db.conn() as c:
        c.execute("delete from jobs where id=?", (j,))
    assert catalog.reconcile(st.db) == {"done": 0, "back": 1}
    assert "už není v historii" in catalog.query_items(st.db)["items"][0]["download_error"]


def test_detail_errors_are_not_mistaken_for_download_errors(st, fake):
    load(st, fake, [e("a")])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='failed', detail_error='geo: nedostupné'")
    assert catalog.query_items(st.db)["items"][0]["download_error"] is None


# ------------------------------------------------------------ celý tok s runnerem
def test_download_flow_saves_into_the_source_folder_and_the_item_disappears(st, fake, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", lambda url, ctx: probe_video(url.split("/")[-1])(url, ctx))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: {}))
    load(st, fake, [e("a"), e("b")], title="Pořad / Řada 1")
    ids = [item(st, "youtube a")["id"], item(st, "youtube b")["id"]]
    catalog.queue_items(st.db, st.runner, ids)
    asyncio.run(run_until(st.runner, lambda: all(j["status"] == "done" for j in jobs(st))))
    done = jobs(st)
    assert [j["status"] for j in done] == ["done", "done"]
    folder = Path(st.settings.get("download_dir")) / "Pořad Řada 1"
    assert all(Path(j["filepath"]).parent == folder for j in done) and folder.is_dir()
    assert catalog.reconcile(st.db) == {"done": 2, "back": 0}
    assert catalog.query_items(st.db)["total"] == 0
    # po „načíst znovu vše“ se staženo z katalogu nabídne s odznakem
    catalog.rescan_source(st.db, st.db.query("select id from catalog_sources")[0]["id"], "all")
    scan(st, "https://x.example/pl", "all")
    assert {i["downloaded_before"] for i in catalog.query_items(st.db)["items"]} == {True}


def test_failed_flow_returns_the_item_to_the_catalog(st, fake, monkeypatch):
    from viddown.resolvers import ResolveError
    monkeypatch.setattr(runner_mod, "probe_url", lambda url, ctx: probe_video("V")(url, ctx))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: ResolveError("Sign in to confirm your age", "login")))
    load(st, fake, [e("a")])
    a = item(st, "youtube a")["id"]
    catalog.queue_items(st.db, st.runner, [a])
    asyncio.run(run_until(st.runner, lambda: jobs(st)[0]["status"] == "failed"))
    catalog.reconcile(st.db)
    it = catalog.query_items(st.db)["items"][0]
    assert it["state"] == "new" and it["download_error"].startswith("stahování selhalo")


# ------------------------------------------------------------ API
def test_api_download_action(rt, data, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.test_subscriptions import State
    from viddown.server import create_app
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    s = State(rt, data)
    s.bot, s.engines_cache = None, (lambda: [])
    c = TestClient(create_app(s))
    (data / "archive.txt").write_text("youtube v0\n", "utf-8")
    with pytest.MonkeyPatch.context() as mp:
        async def probe(url, ctx, timeout=300, playlist_end=None):
            return playlist([e(f"v{i}", f"Video {i}") for i in range(4)], title="Seznam")
        mp.setattr(catalog.ytdlp, "probe", probe)
        catalog.add_sources(rt.db, ["https://x.example/pl"])
        scan(St(rt), "https://x.example/pl")
    r = c.post("/api/catalog/items/action", json={"action": "download", "filter": {"q": "video"}})
    assert r.status_code == 200
    j = r.json()
    assert (j["queued"], j["skipped_downloaded"]) == (3, 1) and j["overview"]["items"] == 4
    assert {x["state"] for x in c.get("/api/catalog/items").json()["items"]} == {"new", "queued"}
    first = c.get("/api/catalog/items", params={"state": "downloaded"}).json()["items"][0]
    r = c.post("/api/catalog/items/action", json={"action": "download", "ids": [first["id"]], "force": True}).json()
    assert r["queued"] == 1 and r["skipped_downloaded"] == 0
    with rt.db.conn() as cx:
        cx.execute("update catalog_items set state='new', job_id=null where id=?", (first["id"],))
    r = c.post("/api/catalog/items/action", json={"action": "download", "ids": [first["id"]], "force": "ano"}).json()     # jen pravé true
    assert r["queued"] == 0 and r["skipped_downloaded"] == 1
    assert {x["source"] for x in rt.db.query("select source from jobs")} == {"catalog"}
    for bad in ({"action": "download"}, {"action": "download", "ids": "1"}, {"action": "download", "filter": 3}):
        assert c.post("/api/catalog/items/action", json=bad).status_code == 400
