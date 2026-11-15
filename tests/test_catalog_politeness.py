"""Katalog: slušnost k zdrojovým serverům – minimální pauza, strop dotazů za hodinu, záložní proxy jen po chybě spojení."""
import asyncio
import time

import pytest

from tests.test_catalog import fake, playlist, rt, scan  # noqa: F401
from tests.test_catalog_anim import st, with_anims  # noqa: F401
from tests.test_catalog_details import info  # noqa: F401
from viddown import catalog, catalogdetails as cd, pagelist
from viddown.config import Settings
from viddown.resolvers import ResolveError


def worker(st, **settings):
    st.settings.update(settings)
    return cd.DetailWorker(st)


# --- minimální pauza -------------------------------------------------------------------------------------
def test_gap_never_goes_below_one_second_even_when_the_setting_is_zero(st, monkeypatch):
    monkeypatch.setattr(cd, "MIN_GAP", 1.0)
    w = worker(st, catalog_gap=0)
    assert all(0.7 <= w.gap() <= 1.3 for _ in range(50))                    # 1 s ± 30 %
    w = worker(st, catalog_gap=5)
    assert all(3.5 <= w.gap() <= 6.5 for _ in range(50))


# --- strop dotazů za hodinu --------------------------------------------------------------------------------
def test_hourly_cap_excludes_the_host_until_old_requests_expire(st):
    w = worker(st, catalog_hour_limit=60)
    for _ in range(59):
        w.note_request("a.example")
    assert not w.over_budget("a.example") and "a.example" not in w.excluded_hosts()
    w.note_request("a.example")
    assert w.over_budget("a.example") and "a.example" in w.excluded_hosts() and "a.example" in w.scan_blocked_hosts()
    assert "a.example" in w.status()["limited"]
    w.hits["a.example"] = type(w.hits["a.example"])(t - 3601 for t in w.hits["a.example"])       # všechny dotazy jsou starší než hodina
    assert not w.over_budget("a.example") and "a.example" not in w.excluded_hosts()
    w2 = worker(st, catalog_hour_limit=0)                                                       # 0 = bez stropu
    for _ in range(5000):
        w2.note_request("b.example")
    assert not w2.over_budget("b.example")


def test_capped_host_is_skipped_when_picking_work(st, fake, info):
    with_anims(st, fake, {"a": None})
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='pending'")
    w = worker(st, catalog_hour_limit=60)
    assert w.pick() is not None
    for _ in range(60):
        w.note_request("example.com")
    assert w.pick() is None                                                                     # web je na stropu: nic se nevybere


# --- záložní proxy -------------------------------------------------------------------------------------------
def test_fallback_worthy_only_for_connection_and_server_errors_not_rate_limits():
    w = cd.DetailWorker
    for ok in ("Connection timed out after 20001 ms", "HTTP 503", "stránku se nepodařilo načíst: boom", "Failed to perform, curl: (28)", "connection reset by peer"):
        assert w.fallback_worthy(ok), ok
    for no in ("HTTP 429 Too Many Requests", "Too many requests", "rate limit exceeded", "HTTP 403 Forbidden", "Video unavailable", "Sign in to confirm"):
        assert not w.fallback_worthy(no), no


def test_details_retry_once_through_the_fallback_proxy_after_a_connection_error(st, fake, info, monkeypatch):
    with_anims(st, fake, {"a": None})
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='pending'")
    w = worker(st, catalog_proxy_fallback="socks5://127.0.0.1:1080", proxy="http://main.example:3128")
    used = []

    async def full_info(url, ctx, timeout=90):
        used.append(ctx.settings.get("proxy"))
        if ctx.settings.get("proxy") != "socks5://127.0.0.1:1080":
            raise ResolveError("Connection timed out after 20001 ms", "network")
        return {"title": "T", "duration": 10}
    monkeypatch.setattr(cd.ytdlp, "full_info", full_info)
    asyncio.run(w.process(st.db.query("select * from catalog_items")[0]))
    assert used == ["http://main.example:3128", "socks5://127.0.0.1:1080"]                      # nejdřív hlavní adresa, jednou záložní
    assert st.db.query("select detail_state from catalog_items")[0]["detail_state"] == "done"
    assert "example.com" in w.status()["fallback_hosts"]


def test_rate_limit_is_not_retried_through_another_address_but_waits(st, fake, info, monkeypatch):
    with_anims(st, fake, {"a": None})
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='pending'")
    w = worker(st, catalog_proxy_fallback="socks5://127.0.0.1:1080")
    used = []

    async def full_info(url, ctx, timeout=90):
        used.append(ctx.settings.get("proxy"))
        raise ResolveError("HTTP Error 429: Too Many Requests", "network")
    monkeypatch.setattr(cd.ytdlp, "full_info", full_info)
    asyncio.run(w.process(st.db.query("select * from catalog_items")[0]))
    assert len(used) == 1                                                                       # žádná druhá adresa
    assert "example.com" in w.backoff and st.db.query("select detail_state from catalog_items")[0]["detail_state"] == "pending"


def test_page_fetch_falls_back_once_and_reports_both_errors(st, monkeypatch):
    w = worker(st, catalog_proxy_fallback="http://fb.example:3128")
    calls = []

    async def fetch(url, settings=None, timeout=30, **kw):
        calls.append((settings or {}).get("proxy") or "")
        raise pagelist.PageError("stránku se nepodařilo načíst: timed out")
    monkeypatch.setattr(cd.pagelist, "fetch", fetch)
    with pytest.raises(pagelist.PageError) as e:
        asyncio.run(w._fetch_page("https://example.com/x", "example.com", False))
    assert calls == ["", "http://fb.example:3128"] and "záložní proxy" in str(e.value)
    calls.clear()

    async def fetch429(url, settings=None, timeout=30, **kw):
        calls.append(1)
        raise pagelist.PageError("stránka vrací chybu HTTP 429")
    monkeypatch.setattr(cd.pagelist, "fetch", fetch429)
    with pytest.raises(pagelist.PageError):
        asyncio.run(w._fetch_page("https://example.com/x", "example.com", False))
    assert len(calls) == 1                                                                      # omezení: bez druhé adresy


def test_fallback_setting_validation_and_hour_limit_range(data):
    s = Settings()
    s.update({"catalog_proxy_fallback": " socks5://127.0.0.1:1080 "})
    assert s.get("catalog_proxy_fallback") == "socks5://127.0.0.1:1080"
    s.update({"catalog_proxy_fallback": ""})
    for bad in ("ftp://x.example", "has space:1", "socks5://"):
        with pytest.raises(ValueError):
            s.update({"catalog_proxy_fallback": bad})
    s.update({"catalog_hour_limit": 0})
    s.update({"catalog_hour_limit": 600})
    for bad in (10, 6000, -1):
        with pytest.raises(ValueError):
            s.update({"catalog_hour_limit": bad})


# --- miniatury: pauza mezi stažením ze stejného serveru ----------------------------------------------------------------
def test_cdn_wait_spaces_downloads_from_the_same_server(st, monkeypatch):
    monkeypatch.setattr(cd, "THUMB_GAP", 0.3)
    w = worker(st)

    async def go():
        t0 = time.monotonic()
        await w._cdn_wait("https://img.example/a.jpg")
        await w._cdn_wait("https://img.example/b.jpg")                                           # stejný server: počká
        same = time.monotonic() - t0
        t1 = time.monotonic()
        await w._cdn_wait("https://other.example/c.jpg")                                         # jiný server: hned
        return same, time.monotonic() - t1
    same, other = asyncio.run(go())
    assert same >= 0.15 and other < same                                                         # jiný server nečeká (srovnání, ne pevný práh)
