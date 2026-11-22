"""Dávka D po hloubkové revizi: zaseknutý NAS nezastaví aplikaci, strop dotazů platí i při stránkování, Telegram nezačíná od nuly po výpadku,
adresy z cizích seznamů, maskování hesel v proxy, žádné čtení API z cizího webu."""
import asyncio
import json
import pathlib
import threading
import time

import pytest

from tests.test_api import client  # noqa: F401
from tests.test_catalog import e
from tests.test_catalog_details import fake, info, images, make, rows, run_until, st, states  # noqa: F401
from tests.test_runner import rt  # noqa: F401
from tests.test_telegram import FakeEngines, bot  # noqa: F401
from viddown import catalog, util
from viddown import catalogdetails as cd
from viddown import runner as runner_mod
from viddown import server as server_mod


# ------------------------------------------------------------ zaseknutý NAS
def test_hanging_target_check_pauses_queue_without_blocking_the_loop(rt, monkeypatch):
    release = threading.Event()
    spawned = []

    def hang(path):
        spawned.append(path)
        release.wait(5)
        return True, ""
    monkeypatch.setattr(runner_mod, "target_available", hang)
    monkeypatch.setattr(runner_mod, "TARGET_TIMEOUT", 0.2)
    async def go():
        t0 = time.monotonic()
        await rt._check_target(rt.settings.all())
        took = time.monotonic() - t0                                         # měří se uvnitř smyčky (po jejím konci asyncio čeká na visící vlákno)
        rt._target_checked = -1e9
        for _ in range(runner_mod.TARGET_FAILS_BEFORE_PAUSE - 1):           # předchozí kontrola ještě visí: nespouští se další vlákno
            rt._target_checked = -1e9
            await rt._check_target(rt.settings.all())
        release.set()
        return took
    took = asyncio.run(go())
    assert took < 2 and rt.queue_paused() and rt.db.kv_get("queue_pause_reason") == "target"
    assert len(spawned) == 1


def test_file_endpoints_answer_504_when_storage_hangs(client, monkeypatch):
    c, st = client
    jid, _ = st.runner.add("https://x.example/v")
    st.db.update(jid, filepath="/nas/slow.mp4")
    real = pathlib.Path.exists
    monkeypatch.setattr(pathlib.Path, "exists", lambda self, **k: time.sleep(1.0) or True if self.name == "slow.mp4" else real(self, **k))
    monkeypatch.setattr(server_mod, "FS_TIMEOUT", 0.2)
    assert c.get(f"/api/file/{jid}").status_code == 504


def test_thumbnail_folder_outage_does_not_mark_thumbnails_as_failed(st, fake, info, images, tmp_path):
    blocker = tmp_path / "soubor"
    blocker.write_text("x")
    st.settings.update({"catalog_thumbs_dir": str(blocker / "thumbs")})       # složku nejde vytvořit (jako odpojený NAS)
    make(st, fake, [e("a", thumbnail="https://img.example/a.jpg")])
    w = cd.DetailWorker(st)
    assert asyncio.run(w.folder_ready()) is False
    assert asyncio.run(w.folder_ready()) is False                             # druhé volání z paměti (nezkouší znovu hned)
    asyncio.run(run_until(st, lambda: states(st)["youtube a"][0] == "done", thumbs=True, worker=w))
    assert rows(st)["youtube a"]["thumb_file"] is None and not images                # nic se nestahovalo a nic se neoznačilo jako nepodařené
    st.settings.update({"catalog_thumbs_dir": str(tmp_path / "ok")})
    w2 = cd.DetailWorker(st)
    assert asyncio.run(w2.folder_ready()) is True


# ------------------------------------------------------------ katalog
def test_multi_page_scan_respects_the_request_budget(monkeypatch):
    fetched = []

    async def fetch(url, settings):
        fetched.append(url)
        return "<html></html>", url
    monkeypatch.setattr(catalog.pagelist, "fetch", fetch)
    monkeypatch.setattr(catalog.pagelist, "page_url", lambda url, cfg, k: f"{url}?p={k}")
    cfg = {"items": [{"url": "https://s.example/v1", "title": "V1"}], "item_regex": "x", "page_param": "p"}
    ctx = type("C", (), {"settings": {}})()
    monkeypatch.setattr(catalog, "SCAN_GATE", lambda host: False)             # strop vyčerpán
    res = asyncio.run(catalog._page_entries("https://s.example/list", ctx, cfg, None))
    assert fetched == [] and res["complete"] is False and len(res["entries"]) == 1


def test_scan_gate_counts_requests_and_blocks_over_the_hourly_limit(st):
    st.settings.update({"catalog_hour_limit": 60})
    w = cd.DetailWorker(st)
    got = [w.scan_gate("x.example") for _ in range(62)]
    assert got[:60] == [True] * 60 and got[60:] == [False, False]


def test_private_addresses_from_a_listing_are_not_requested(st, fake, info):
    st.settings.update({"catalog_slow_browser": False})
    make(st, fake, [e("a", url="http://192.168.1.5/admin"), e("b", url="https://ok.example/v/1")])
    asyncio.run(run_until(st, lambda: all(v[0] != "pending" for v in states(st).values())))
    r = rows(st)
    assert r["youtube a"]["detail_state"] == "failed" and "mimo veřejný internet" in r["youtube a"]["detail_error"]
    assert r["youtube b"]["detail_state"] == "done"
    assert "http://192.168.1.5/admin" not in [c[0] for c in info.calls]


# ------------------------------------------------------------ Telegram a API
def test_telegram_keeps_the_update_offset_across_reconnects(bot, monkeypatch):
    calls = []
    state = {"polls": 0}

    async def call(method, http_timeout=30, **p):
        calls.append((method, dict(p)))
        if method == "getMe":
            return {"username": "b"}
        if method == "getUpdates":
            state["polls"] += 1
            if state["polls"] == 1:
                return [{"update_id": 7}]
            if state["polls"] == 2:
                raise RuntimeError("výpadek spojení")
            stop.set()
            return []
        return {}
    bot.call = call

    async def no_wait(stop_, sec):
        await asyncio.sleep(0)
    bot._wait = no_wait

    async def handle(u):
        return None
    bot.handle = handle
    bot.secrets.set_telegram_token("123:abc")
    stop = asyncio.Event()
    asyncio.run(asyncio.wait_for(bot.run(stop), 10))
    polls = [p for m, p in calls if m == "getUpdates"]
    assert "offset" not in polls[0] and polls[2].get("offset") == 8              # po výpadku se nezačíná od nuly (nic se nezpracuje dvakrát)


def test_cross_site_requests_to_the_api_are_refused(client):
    c, st = client
    assert c.get("/api/state").status_code == 200
    assert c.get("/api/state", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert c.get("/api/state", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_proxy_password_is_masked_in_exports_and_helper(client):
    assert util.mask_proxy("socks5://user:tajne@proxy.example:1080") == "socks5://user:***@proxy.example:1080"
    assert util.mask_proxy("http://proxy.example:3128") == "http://proxy.example:3128"
    c, st = client
    st.settings.update({"proxy": "socks5://user:tajne@proxy.example:1080"})
    out = c.get("/api/settings/export").json()
    assert "tajne" not in json.dumps(out) and out["proxy"].endswith("@proxy.example:1080")


def test_bulk_cancel_removes_queued_items_and_ignores_unknown_ids(client):
    c, st = client
    ids = [st.runner.add(f"https://x.example/{i}")[0] for i in range(3)]
    r = c.post("/api/jobs/bulk-cancel", json={"ids": [*ids[:2], 9999]})
    assert r.status_code == 200 and r.json()["cancelled"] == 2
    assert [st.db.get(i)["status"] for i in ids][2] != "cancelled"


def test_startup_cleanup_of_a_hanging_temp_folder_does_not_block_the_loop(rt, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(rt, "_cleanup_staging", lambda: release.wait(5))
    monkeypatch.setattr(runner_mod.asyncio, "wait_for", asyncio.wait_for)

    async def go():
        beats = []

        async def heartbeat():
            for _ in range(5):
                beats.append(1)
                await asyncio.sleep(0.05)
        hb = asyncio.create_task(heartbeat())
        cleanup = asyncio.create_task(rt._finish_cancelling_async())
        await hb
        release.set()
        await cleanup
        return len(beats)
    assert asyncio.run(go()) == 5                                             # smyčka běžela, i když úklid visel
