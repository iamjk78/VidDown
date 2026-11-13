"""Katalog, etapa 3: výběr položek (výčtem i filtrem s výjimkami) a hromadné odstranění."""
import pytest

from tests.test_catalog import add, client, e, fake, filled, keys, playlist, rt, scan, st  # noqa: F401
from viddown import catalog


def ids(db, **where):
    return {r["title"]: r["id"] for r in db.query("select id, title from catalog_items")}


def test_select_by_ids_validates_and_dedupes(filled):
    assert catalog.select_ids(filled.db, {"ids": [3, 1, 3]}) == [3, 1]
    for bad in ({"ids": "1"}, {"ids": [True]}, {"ids": [0]}, {"ids": [-1]}, {"ids": [2 ** 70]}, {"ids": [1.5]}, {"ids": [None]},
                [], "x", {}, {"filter": "x"}, {"filter": {"source": True}}, {"filter": {"q": 5}}, {"filter": {"res": "1080"}},
                {"filter": {"state": [1]}}, {"filter": {}, "exclude": "x"}):
        with pytest.raises(ValueError):
            catalog.select_ids(filled.db, bad)


def test_select_by_filter_matches_what_the_listing_shows_and_honours_exclude(filled):
    db = filled.db
    shown = catalog.query_items(db, q="pergola", limit=500)
    assert catalog.select_ids(db, {"filter": {"q": "pergola"}}) == sorted(i["id"] for i in shown["items"])
    got = catalog.select_ids(db, {"filter": {"res": ["480", "2160"]}})
    assert {i["title"] for i in catalog.query_items(db, res=["480", "2160"])["items"]} == {r["title"] for r in db.query(
        f"select title from catalog_items where id in ({','.join(map(str, got))})")}
    everything = catalog.select_ids(db, {"filter": {}})
    assert len(everything) == 5
    first = everything[0]
    assert catalog.select_ids(db, {"filter": {}, "exclude": [first, first, 999999]}) == everything[1:]
    sid = db.query("select id from catalog_sources where title='Béčko'")[0]["id"]
    assert len(catalog.select_ids(db, {"filter": {"source": sid}})) == 2
    # skryté (odstraněné) položky se výchozím filtrem nevybírají
    with db.conn() as c:
        c.execute("update catalog_items set state='removed' where id=?", (first,))
    assert first not in catalog.select_ids(db, {"filter": {}})


def test_select_by_filter_refuses_an_absurd_amount(filled, monkeypatch):
    monkeypatch.setattr(catalog, "MAX_SELECT", 3)
    with pytest.raises(ValueError, match="too many"):
        catalog.select_ids(filled.db, {"filter": {}})
    with pytest.raises(ValueError, match="too many"):
        catalog.select_ids(filled.db, {"ids": [1, 2, 3, 4]})


def test_remove_items_hides_them_deletes_thumbnails_and_skips_queued(filled, tmp_path):
    db = filled.db
    m = ids(db)
    folder = tmp_path / "thumbs"
    folder.mkdir()
    for title in ("Zahradní pergola", "Opravy kol"):
        (folder / f"{m[title]}.jpg").write_bytes(b"x")
        with db.conn() as c:
            c.execute("update catalog_items set thumb_file=? where id=?", (f"{m[title]}.jpg", m[title]))
    with db.conn() as c:
        c.execute("update catalog_items set state='queued', job_id=7 where id=?", (m["Test kombíku"],))
        c.execute("update catalog_items set state='gone' where id=?", (m["Dokument o tunelu"],))
    res = catalog.remove_items(db, [m["Zahradní pergola"], m["Opravy kol"], m["Test kombíku"], m["Dokument o tunelu"], 99999], folder)
    assert res == {"removed": 3, "skipped": 2}                                    # ve frontě a neexistující se přeskočí
    rows = {r["title"]: r for r in db.query("select * from catalog_items")}
    assert [rows[t]["state"] for t in ("Zahradní pergola", "Opravy kol", "Dokument o tunelu")] == ["removed"] * 3
    assert rows["Test kombíku"]["state"] == "queued" and rows["Test kombíku"]["job_id"] == 7
    assert rows["Zahradní pergola"]["thumb_file"] is None and not list(folder.iterdir())
    assert catalog.remove_items(db, [m["Opravy kol"]], folder) == {"removed": 0, "skipped": 1}      # podruhé už nic
    assert catalog.remove_items(db, [], folder) == {"removed": 0, "skipped": 0}
    assert catalog.query_items(db)["total"] == 2


def test_removed_items_come_back_as_rejected_only_on_reload(filled, fake):
    db = filled.db
    m = ids(db)
    catalog.remove_items(db, [m["Opravy kol"]])
    sid = db.query("select id from catalog_sources where title='Zdroj Alfa'")[0]["id"]
    scan(filled, "https://x.example/a", "new")                                     # běžné obnovení je nevrátí
    assert db.query("select state from catalog_items where title='Opravy kol'")[0]["state"] == "removed"
    catalog.rescan_source(db, sid, "all")
    scan(filled, "https://x.example/a", "all")
    row = db.query("select state, rejected_before from catalog_items where title='Opravy kol'")[0]
    assert row["state"] == "new" and row["rejected_before"] == 1


def test_api_bulk_remove_by_ids_and_by_filter(client, fake, tmp_path):
    c, s = client
    from tests.test_catalog import St
    fake["https://x.example/a"] = playlist([e(f"v{i}", f"Video {i}") for i in range(6)], title="Zdroj")
    catalog.add_sources(s.db, ["https://x.example/a"])
    st = St(s.data)
    st.db = s.db
    scan(st, "https://x.example/a")
    items = c.get("/api/catalog/items").json()["items"]
    r = c.post("/api/catalog/items/action", json={"action": "remove", "ids": [items[0]["id"], items[1]["id"], 999999]})
    assert r.status_code == 200 and (r.json()["removed"], r.json()["skipped"]) == (2, 1) and r.json()["overview"]["items"] == 4
    keep = c.get("/api/catalog/items").json()["items"][0]["id"]
    r = c.post("/api/catalog/items/action", json={"action": "remove", "filter": {"q": "video"}, "exclude": [keep]})
    assert r.json()["removed"] == 3
    assert [i["id"] for i in c.get("/api/catalog/items").json()["items"]] == [keep]
    assert c.get("/api/catalog/items", params={"state": "gone"}).json()["total"] == 0


@pytest.mark.parametrize("body", [[1], "x", {}, {"action": "smazat", "ids": [1]}, {"action": "remove"}, {"action": "remove", "ids": "1"},
                                  {"action": "remove", "ids": [True]}, {"action": "remove", "filter": 5}, {"action": "remove", "ids": [2 ** 80]}])
def test_api_action_rejects_bad_requests(client, body):
    c, s = client
    assert c.post("/api/catalog/items/action", json=body).status_code == 400


def test_api_action_rejects_non_json(client):
    c, s = client
    assert c.post("/api/catalog/items/action", content=b"neni json", headers={"Content-Type": "application/json"}).status_code == 400
