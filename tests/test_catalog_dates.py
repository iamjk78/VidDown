"""Katalog: datum zveřejnění (řazení, filtr stáří, doplnění) a vyřízený zdroj (Odebrat / Ponechat)."""
import asyncio
import datetime
import time

from tests.test_catalog import client, e, fake, playlist, rt, scan, st  # noqa: F401
from viddown import catalog, catalogdetails

DAY = 86400


def utc(y, m, d):
    return datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc).timestamp()


def make(st, fake, entries, url="https://x.example/a", title="Zdroj"):
    fake[url] = playlist(entries, title=title)
    catalog.add_sources(st.db, [url])
    scan(st, url)
    return st.db.query("select id from catalog_sources where url=?", (url,))[0]["id"]


def set_pub(st, title_part, value):
    with st.db.conn() as c:
        c.execute("update catalog_items set published_at=? where title like ?", (value, f"%{title_part}%"))


# --- zjištění data ---------------------------------------------------------------------------------
def test_published_ts_prefers_timestamps_then_dates_and_ignores_nonsense():
    now = time.time()
    assert catalog.published_ts({"release_timestamp": 1700000000, "timestamp": 1600000000}) == 1700000000
    assert catalog.published_ts({"timestamp": 1600000000.5}) == 1600000000.5
    assert catalog.published_ts({"upload_date": "20231105"}) == utc(2023, 11, 5)
    assert catalog.published_ts({"release_date": "20240102", "upload_date": "20231105"}) == utc(2024, 1, 2)
    assert catalog.published_ts({"upload_date": "2023-11-05"}) is None                 # jen RRRRMMDD
    assert catalog.published_ts({"upload_date": "20231345"}) is None                   # neexistující den
    assert catalog.published_ts({"timestamp": 1000}) is None                           # před rokem 1990
    assert catalog.published_ts({"timestamp": now + 10 * DAY}) is None                 # z budoucnosti
    assert catalog.published_ts({"timestamp": True}) is None and catalog.published_ts(None) is None and catalog.published_ts({}) is None


def test_listing_stores_date_and_migration_added_columns(st, fake):
    make(st, fake, [e("a1", timestamp=1700000000), e("a2")])
    rows = {r["title"]: r["published_at"] for r in st.db.query("select title, published_at from catalog_items")}
    assert rows == {"Video a1": 1700000000, "Video a2": None}
    assert st.db.query("pragma table_info(catalog_sources)") and "keep_total" in {r["name"] for r in st.db.query("pragma table_info(catalog_sources)")}


def test_details_store_date_and_zero_means_site_has_none(st, fake):
    make(st, fake, [e("a1"), e("a2")])
    d = catalogdetails.DetailWorker(st)
    items = st.db.query("select * from catalog_items order by id")
    asyncio.run(d._store(dict(items[0]), {"title": "T1", "upload_date": "20240301"}))
    asyncio.run(d._store(dict(items[1]), {"title": "T2"}))
    got = {r["id"]: r["published_at"] for r in st.db.query("select id, published_at from catalog_items")}
    assert got[items[0]["id"]] == utc(2024, 3, 1)
    assert got[items[1]["id"]] == 0                                                    # zkoušeno, web datum nenabízí
    out = {i["id"]: i["published"] for i in catalog.query_items(st.db)["items"]}
    assert out[items[0]["id"]] == utc(2024, 3, 1) and out[items[1]["id"]] is None


def test_refill_dates_only_retries_videos_with_unknown_date(st, fake):
    sid = make(st, fake, [e("a1"), e("a2"), e("a3")])
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")
    set_pub(st, "a2", 0)                      # web datum nenabízí
    set_pub(st, "a3", utc(2024, 1, 1))        # datum známe
    assert catalogdetails.refill_dates(st.db, sid) == {"details": 1}
    pend = st.db.query("select title from catalog_items where detail_state='pending'")
    assert [r["title"] for r in pend] == ["Video a1"]
    assert catalogdetails.refill_dates(st.db, sid + 1) == {"details": 0}              # jiný zdroj


# --- řazení a filtr --------------------------------------------------------------------------------
def test_sort_by_published_both_directions_unknown_last(st, fake):
    make(st, fake, [e("a1"), e("a2"), e("a3"), e("a4")])
    set_pub(st, "a1", utc(2024, 1, 1))
    set_pub(st, "a2", utc(2025, 6, 1))
    set_pub(st, "a3", 0)
    titles = lambda d: [i["title"] for i in catalog.query_items(st.db, sort="published", direction=d)["items"]]  # noqa: E731
    assert titles("desc")[:2] == ["Video a2", "Video a1"] and set(titles("desc")[2:]) == {"Video a3", "Video a4"}     # nejnovější první
    assert titles("asc")[:2] == ["Video a1", "Video a2"] and set(titles("asc")[2:]) == {"Video a3", "Video a4"}       # nejstarší první


def test_sort_by_published_within_one_source(st, fake):
    a = make(st, fake, [e("a1"), e("a2")], "https://x.example/a", "A")
    make(st, fake, [e("b1"), e("b2")], "https://x.example/b", "B")
    set_pub(st, "a1", utc(2020, 1, 1))
    set_pub(st, "a2", utc(2021, 1, 1))
    set_pub(st, "b1", utc(2022, 1, 1))
    got = catalog.query_items(st.db, source=a, sort="published", direction="desc")["items"]
    assert [i["title"] for i in got] == ["Video a2", "Video a1"]


def test_age_filter_and_selection_filter(st, fake):
    make(st, fake, [e("a1"), e("a2"), e("a3"), e("a4")])
    now = time.time()
    set_pub(st, "a1", now - 2 * DAY)
    set_pub(st, "a2", now - 20 * DAY)
    set_pub(st, "a3", now - 200 * DAY)
    set_pub(st, "a4", 0)
    titles = lambda age: {i["title"] for i in catalog.query_items(st.db, age=age)["items"]}  # noqa: E731
    assert titles("week") == {"Video a1"}
    assert titles("month") == {"Video a1", "Video a2"}
    assert titles("year") == {"Video a1", "Video a2", "Video a3"}
    assert len(titles("")) == 4 and len(titles("nesmysl")) == 4                       # neznámá hodnota = bez filtru
    ids = catalog.select_ids(st.db, {"filter": {"age": "month"}})                      # hromadná akce se řídí stejným filtrem
    assert len(ids) == 2


# --- vyřízený zdroj --------------------------------------------------------------------------------
def src_out(st, sid):
    return next(s for s in catalog.sources_out(st.db)["sources"] if s["id"] == sid)


def test_source_is_exhausted_only_when_nothing_is_left_and_keep_silences_until_new_videos(st, fake):
    sid = make(st, fake, [e("a1"), e("a2")])
    assert src_out(st, sid)["exhausted"] is False                                      # videa k výběru zbývají
    ids = [r["id"] for r in st.db.query("select id from catalog_items order by id")]
    catalog.remove_items(st.db, [ids[0]])
    assert src_out(st, sid)["exhausted"] is False                                      # jedno ještě zbývá
    with st.db.conn() as c:
        c.execute("update catalog_items set state='queued' where id=?", (ids[1],))
    assert src_out(st, sid)["exhausted"] is False                                      # čeká ve frontě stahování
    with st.db.conn() as c:
        c.execute("update catalog_items set state='done' where id=?", (ids[1],))
    assert src_out(st, sid)["exhausted"] is True                                       # staženo: zdroj je vyřízený
    assert catalog.keep_source(st.db, sid) is True
    assert src_out(st, sid)["exhausted"] is False                                      # Ponechat: už se neptá
    fake["https://x.example/a"] = playlist([e("a1"), e("a2"), e("a3")], title="Zdroj")
    catalog.rescan_source(st.db, sid, "new")
    scan(st, "https://x.example/a")
    assert src_out(st, sid)["exhausted"] is False                                      # nové video k výběru
    new = st.db.query("select id from catalog_items where title='Video a3'")[0]["id"]
    catalog.remove_items(st.db, [new])
    assert src_out(st, sid)["exhausted"] is True                                       # zase vyřízený: celkový počet je jiný než při „Ponechat“


def test_empty_or_scanning_source_is_not_exhausted(st, fake):
    sid = make(st, fake, [])
    assert src_out(st, sid)["exhausted"] is False                                      # zdroj bez videí se neřeší
    sid2 = make(st, fake, [e("b1")], "https://x.example/b", "B")
    ids = [r["id"] for r in st.db.query("select id from catalog_items where source_id=?", (sid2,))]
    catalog.remove_items(st.db, ids)
    with st.db.conn() as c:
        c.execute("update catalog_sources set status='scanning' where id=?", (sid2,))
    assert src_out(st, sid2)["exhausted"] is False                                     # právě se zjišťuje


def test_api_keep_and_dates_refill_and_age_param(client):
    c, s = client
    assert c.post("/api/catalog/sources/999/keep").status_code == 404
    assert c.post("/api/catalog/dates/refill", json={"source": True}).status_code == 400
    r = c.post("/api/catalog/dates/refill")
    assert r.status_code == 200 and r.json()["details"] == 0 and "overview" in r.json()
    assert c.get("/api/catalog/items?sort=published&dir=desc&age=month").status_code == 200
    st_ = c.get("/api/catalog").json()["details"]
    assert "no_date" in st_ and "have_date" in st_


# --- filtr délky -----------------------------------------------------------------------------------
def test_duration_filter_uses_adjoining_intervals_union_and_selection(st, fake):
    lens = {"d1": 5, "d2": 20, "d3": 21, "d4": 60, "d5": 61, "d6": 300, "d7": 3600, "d8": 3601, "d9": None}
    make(st, fake, [e(k, duration=v) for k, v in lens.items()])
    got = lambda *d: sorted(i["title"][-2:] for i in catalog.query_items(st.db, dur=list(d))["items"])  # noqa: E731
    assert got("20") == ["d1", "d2"]                                    # do 20 s včetně 20
    assert got("60") == ["d3", "d4"]                                    # navazující: 20 s < délka ≤ 60 s
    assert got("120") == ["d5"] and got("300") == ["d6"]
    assert got("3600") == ["d7"] and got("over") == ["d8"] and got("unknown") == ["d9"]
    assert got("20", "over", "unknown") == ["d1", "d2", "d8", "d9"]       # více tlačítek = sjednocení
    assert len(got()) == 9 and len(got("nesmysl")) == 9                  # bez filtru / neznámá hodnota
    assert len(catalog.select_ids(st.db, {"filter": {"dur": ["60", "over"]}})) == 3
    import pytest
    with pytest.raises(ValueError):
        catalog.select_ids(st.db, {"filter": {"dur": "60"}})
    assert catalog.query_items(st.db, sort="duration", dur=["60"])["total"] == 2


def test_api_dur_param(client):
    c, s = client
    assert c.get("/api/catalog/items?dur=20,60,over").status_code == 200
