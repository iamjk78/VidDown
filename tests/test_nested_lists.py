"""Zdroje, jejichž položky jsou další playlisty (záložka „Playlisty“): rozpoznání, Katalog (výběr), fronta (podsložky)."""
import asyncio

import pytest

from tests.test_catalog import client, e, fake, playlist, rt, scan, st  # noqa: F401
from tests.test_runner import rt as qrt, run_until  # noqa: F401
from viddown import catalog, nested, probe as probe_mod
from viddown import runner as runner_mod

TAB = "https://x.example/@kanal/playlists"


def pl(i, title=None, ie="YoutubeTab"):
    return {"_type": "url", "ie_key": ie, "id": f"PL{i}", "url": f"https://www.youtube.com/playlist?list=PL{i}", "title": title or f"Playlist {i}"}


def tab(entries, title="Kanál - Playlisty"):
    return {"_type": "playlist", "title": title, "extractor_key": "YoutubeTab", "entries": entries}


# --- rozpoznání --------------------------------------------------------------------------------------
def test_is_list_entry_and_list_infos():
    assert nested.is_list_entry(pl(1)) and nested.is_list_entry({"url": "https://www.youtube.com/playlist?list=ABC_1-x"})
    assert not nested.is_list_entry(e("v1"))                                            # video
    assert not nested.is_list_entry({"_type": "playlist", "entries": [e("v1")], "url": "https://www.youtube.com/playlist?list=ABC"})   # vložené položky zploští jiný kód
    assert not nested.is_list_entry(None) and not nested.is_list_entry({"url": "https://www.youtube.com/watch?v=abcdefghijk"})
    got = nested.list_infos([pl(1), pl(1), None, e("v1"), pl(2, "B")])
    assert [x["url"] for x in got] == ["https://www.youtube.com/playlist?list=PL1", "https://www.youtube.com/playlist?list=PL2"]
    assert got[1] == {"url": "https://www.youtube.com/playlist?list=PL2", "title": "B", "id": "PL2"}


# --- Katalog -----------------------------------------------------------------------------------------
def add(st, fake, entries, url=TAB):
    fake[url] = tab(entries)
    catalog.add_sources(st.db, [url])
    scan(st, url)
    return st.db.query("select * from catalog_sources where url=?", (url,))[0]


def test_catalog_source_with_playlists_waits_for_choice_and_adds_no_items(st, fake):
    s = add(st, fake, [pl(1, "A"), pl(2, "B"), pl(3, "C")])
    assert s["status"] == "choose" and s["kind"] == "playlists" and s["title"] == "Kanál - Playlisty"
    assert st.db.query("select count(*) n from catalog_items")[0]["n"] == 0             # playlisty se nesmí tvářit jako videa
    out = catalog.sources_out(st.db)["sources"][0]
    assert out["status"] == "choose" and [p["title"] for p in out["playlists"]] == ["A", "B", "C"] and out["exhausted"] is False


def test_choose_status_is_not_rescanned_automatically(st, fake):
    s = add(st, fake, [pl(1)])
    with st.db.conn() as c:
        c.execute("update catalog_sources set last_scan=1")
    assert catalog.auto_refresh(st.db, 1) == 0 and catalog.rescan_all(st.db) == 0
    assert catalog.claim_source(st.db) is None


def test_expand_adds_selected_playlists_as_sources_and_removes_the_list(st, fake):
    s = add(st, fake, [pl(1, "A"), pl(2, "B"), pl(3, "C")])
    res = catalog.expand_source(st.db, s["id"], [pl(1)["url"], pl(3)["url"], "https://evil.example/x", pl(1)["url"]])
    assert len(res["added"]) == 2 and res["skipped"] == []                              # cizí adresa a duplicita se ignorují
    urls = [r["url"] for r in st.db.query("select url from catalog_sources order by id")]
    assert urls == [pl(1)["url"], pl(3)["url"]]                                         # původní zdroj je pryč, playlisty jsou zdroje
    assert all(r["status"] == "queued" for r in st.db.query("select status from catalog_sources"))
    assert catalog.expand_source(st.db, s["id"], [pl(2)["url"]]) is None                # podruhé už není co rozbalit


def test_expand_refuses_normal_sources(st, fake):
    fake["https://x.example/a"] = playlist([e("a1")], title="Zdroj")
    catalog.add_sources(st.db, ["https://x.example/a"])
    scan(st, "https://x.example/a")
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    assert catalog.expand_source(st.db, sid, ["https://x.example/a"]) is None
    assert st.db.query("select count(*) n from catalog_sources")[0]["n"] == 1


def test_mixed_source_ignores_playlist_links_and_keeps_videos(st, fake):
    s = add(st, fake, [e("v1"), pl(1), e("v2")], url="https://x.example/mixed")
    assert s["status"] == "done"
    assert st.db.query("select count(*) n from catalog_items")[0]["n"] == 2


def test_more_than_the_limit_is_cut(st, fake):
    s = add(st, fake, [pl(i) for i in range(nested.MAX_LISTS + 20)])
    assert len(catalog.sources_out(st.db)["sources"][0]["playlists"]) == nested.MAX_LISTS


def test_api_expand(client):
    c, s = client
    assert c.post("/api/catalog/sources/999/expand", json={"urls": []}).status_code == 404
    assert c.post("/api/catalog/sources/1/expand", json={"urls": "x"}).status_code == 400


# --- fronta ------------------------------------------------------------------------------------------
def test_probe_expands_playlists_into_videos_with_group(monkeypatch):
    async def fake_probe(url, ctx, timeout=300, playlist_end=None):
        if url == TAB:
            return tab([pl(1, "Alfa"), pl(2, "Beta"), pl(3, "Rozbitý")])
        if url.endswith("PL3"):
            raise probe_mod.ResolveError("nelze", "network")
        n = url[-1]
        return {"_type": "playlist", "title": f"Playlist {n}", "entries": [e(f"v{ 'a' if n == '1' else 'b'}"), e("sdilene")]}

    async def full(url, ctx, timeout=120):
        return {"title": "x", "height": 720, "formats": []}
    monkeypatch.setattr(probe_mod.ytdlp, "probe", fake_probe)
    monkeypatch.setattr(probe_mod.ytdlp, "full_info", full)
    res = asyncio.run(probe_mod._probe_ytdlp(TAB, __import__("types").SimpleNamespace(settings={})))
    assert res["type"] == "playlist" and res["count"] == 3
    got = {(x["group"], x["url"].rsplit("/", 1)[-1]) for x in res["entries"]}
    assert got == {("Alfa", "va"), ("Alfa", "sdilene"), ("Beta", "vb")}                  # sdílené video je jen jednou, rozbitý playlist se přeskočil
    assert {x["group"] for x in res["entries"]} == {"Alfa", "Beta"}


def test_runner_puts_each_playlist_into_its_own_subfolder(qrt, monkeypatch):
    rt = qrt
    entries = [{"url": "https://x/a1", "title": "A1", "group": "Alfa"}, {"url": "https://x/b1", "title": "B1", "group": "Beta / 2"},
               {"url": "https://x/c1", "title": "C1"}]

    async def probe(url, ctx):
        return {"type": "playlist", "method": "ytdlp", "title": "Kanál", "count": 3, "entries": [dict(x) for x in entries], "height": 720}
    monkeypatch.setattr(runner_mod, "probe_url", probe)
    p, _ = rt.add("https://x/tab")
    asyncio.run(run_until(rt, lambda: rt.db.get(p)["status"] in ("confirm", "expanded")))
    if rt.db.get(p)["status"] == "confirm":
        assert rt.confirm(p)
    subs = {k["url"]: k["subdir"] for k in rt.db.children(p)}
    assert subs == {"https://x/a1": "Kanál/Alfa", "https://x/b1": "Kanál/Beta 2", "https://x/c1": "Kanál"}     # bez playlistu zůstává složka kanálu
