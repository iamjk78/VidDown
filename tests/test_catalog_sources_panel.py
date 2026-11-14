"""Katalog: odebrání zdroje se zachováním videí (odpojení), Obnovit všechny, odebrané zdroje ve filtru."""
import asyncio

import pytest

from tests.test_catalog import client, e, fake, playlist, rt, scan, st  # noqa: F401
from viddown import catalog


def two_sources(st, fake):
    for u, t in (("https://x.example/a", "Zdroj A"), ("https://x.example/b", "Zdroj B")):
        fake[u] = playlist([e(f"{t[-1]}1"), e(f"{t[-1]}2")], title=t)
        catalog.add_sources(st.db, [u])
        scan(st, u)


def src(st, url):
    return st.db.query("select * from catalog_sources where url=?", (url,))[0]


def test_remove_with_videos_deletes_everything_but_keeps_other_sources(st, fake):
    two_sources(st, fake)
    a = src(st, "https://x.example/a")["id"]
    assert catalog.delete_source(st.db, a) is True
    assert [s["title"] for s in catalog.sources_out(st.db)["sources"]] == ["Zdroj B"]
    assert st.db.query("select count(*) n from catalog_items")[0]["n"] == 2
    assert catalog.delete_source(st.db, a) is False


def test_remove_keeping_videos_detaches_the_source(st, fake):
    two_sources(st, fake)
    a = src(st, "https://x.example/a")["id"]
    assert catalog.delete_source(st.db, a, keep_items=True) is True
    out = catalog.sources_out(st.db)
    assert [s["title"] for s in out["sources"]] == ["Zdroj B"]                                # ze seznamu zdrojů zmizel
    assert out["detached"] == [{"id": a, "title": "Zdroj A", "items": 2}] and out["items"] == 4  # videa jsou dál započítaná
    items = catalog.query_items(st.db)["items"]
    assert len(items) == 4 and {i["source_title"] for i in items} == {"Zdroj A", "Zdroj B"}        # zůstala v seznamu i s názvem zdroje
    assert {i["title"] for i in catalog.query_items(st.db, source=a)["items"]} == {"Video A1", "Video A2"}   # jdou filtrovat
    assert catalog.query_items(st.db, source=a)["items"][0]["source_folder"] == "Zdroj A"          # složka pro stahování zůstává
    assert catalog.delete_source(st.db, a, keep_items=True) is False                               # podruhé nic


def test_detached_source_is_never_scanned_refreshed_or_rescanned(st, fake):
    two_sources(st, fake)
    a = src(st, "https://x.example/a")["id"]
    catalog.delete_source(st.db, a, keep_items=True)
    with st.db.conn() as c:
        c.execute("update catalog_sources set last_scan=1")                                        # dávno zjištěné: automatika by je obnovila
    assert catalog.auto_refresh(st.db, 1) == 1                                                     # jen zdroj B
    assert src(st, "https://x.example/a")["status"] == "detached"
    assert catalog.rescan_source(st.db, a, "new") is None                                          # ruční obnovení odpojeného zdroje nejde
    assert catalog.rescan_all(st.db) == 1 and src(st, "https://x.example/a")["status"] == "detached"
    assert catalog.claim_source(st.db)["url"] == "https://x.example/b"


def test_scan_finishing_after_detach_does_not_reattach(st, fake):
    two_sources(st, fake)
    a = src(st, "https://x.example/a")
    with st.db.conn() as c:
        c.execute("update catalog_sources set status='scanning' where id=?", (a["id"],))
    catalog.delete_source(st.db, a["id"], keep_items=True)                                         # odebráno během zjišťování
    asyncio.run(catalog.scan_one(st, {**a, "status": "scanning", "scan_mode": "new"}))
    assert src(st, "https://x.example/a")["status"] == "detached"


def test_adding_the_same_address_reconnects_a_detached_source(st, fake):
    two_sources(st, fake)
    a = src(st, "https://x.example/a")["id"]
    catalog.delete_source(st.db, a, keep_items=True)
    res = catalog.add_sources(st.db, ["https://x.example/a"])
    assert res["reloaded"] == [a] and src(st, "https://x.example/a")["status"] == "queued"
    scan(st, "https://x.example/a")
    out = catalog.sources_out(st.db)
    assert sorted(s["title"] for s in out["sources"]) == ["Zdroj A", "Zdroj B"] and out["detached"] == []
    assert st.db.query("select count(*) n from catalog_items where source_id=?", (a,))[0]["n"] == 2         # bez duplicit


def test_detached_source_without_visible_videos_is_not_listed(st, fake):
    two_sources(st, fake)
    a = src(st, "https://x.example/a")["id"]
    catalog.delete_source(st.db, a, keep_items=True)
    catalog.remove_items(st.db, [i["id"] for i in catalog.query_items(st.db, source=a)["items"]])
    assert catalog.sources_out(st.db)["detached"] == []


def test_rescan_all_queues_idle_sources_only(st, fake):
    two_sources(st, fake)
    with st.db.conn() as c:
        c.execute("update catalog_sources set status='scanning' where url like '%/b'")
    assert catalog.rescan_all(st.db) == 1
    assert {s["url"][-1]: s["status"] for s in st.db.query("select url, status from catalog_sources")} == {"a": "queued", "b": "scanning"}
    assert st.db.query("select manual from catalog_sources where url like '%/a'")[0]["manual"] == 1


def test_api_delete_keep_items_and_refresh_all(client):
    c, s = client
    with s.db.conn() as cx:
        cx.execute("insert into catalog_sources(id,url,status,added_at,title,folder) values (1,'https://s.example/p','done',1,'Z','Z')")
        cx.execute("insert into catalog_items(id,source_id,key,url,state,detail_state,added_at,updated_at) values (1,1,'k','https://s.example/v','new','done',1,1)")
    r = c.post("/api/catalog/sources/refresh").json()
    assert r["queued"] == 1 and r["overview"]["scanning"] == 1
    r = c.delete("/api/catalog/sources/1?keep_items=1")
    assert r.status_code == 200 and r.json()["sources"] == [] and r.json()["detached"][0]["items"] == 1
    assert c.get("/api/catalog/items").json()["total"] == 1
    assert c.post("/api/catalog/sources/1/refresh").status_code == 404
    assert c.delete("/api/catalog/sources/1?keep_items=1").status_code == 404
    assert c.delete("/api/catalog/sources/1").status_code == 200                                   # úplné odebrání odpojeného zdroje
    assert c.get("/api/catalog/items").json()["total"] == 0
