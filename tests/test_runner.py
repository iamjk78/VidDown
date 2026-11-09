"""Fronta: pořadí, fallback, opakování, pauza, zrušení, potvrzení – s falešnými metodami (bez sítě)."""
import asyncio
import json
import time
from pathlib import Path

import pytest

from viddown import runner as runner_mod
from viddown.config import Settings
from viddown.db import DB
from viddown.resolvers import Cancelled, ResolveError


class FakeEngines:
    class E:
        def bin_path(self, *a, **k):
            return None

    def get(self, name):
        return self.E()

    def update_all(self):
        return {}


@pytest.fixture()
def rt(data, monkeypatch, tmp_path):
    s = Settings()
    s.update({"download_dir": str(tmp_path / "dl"), "sleep_min": 0, "sleep_max": 0, "concurrency": 1,
              "engine_auto_update": False, "min_free_gb": 0, "playlist_confirm_threshold": 3})
    db = DB(data / "t.db")
    r = runner_mod.Runner(db, s, FakeEngines(), data)
    events = []

    class L:
        def on_error(self, job, msg): events.append(("error", job["id"], msg))
        def on_summary(self, parent, failed, total): events.append(("summary", parent["id"], len(failed), total))
        def on_probe(self, job, res): events.append(("probe", job["id"], job["status"]))
    r.listeners.append(L())
    r.events = events
    return r


def fake_download(behaviour):
    async def dl(url, info, ctx, staging, name, rate, on_progress, holder, audio_only=None):
        b = behaviour(url)
        if isinstance(b, Exception):
            raise b
        holder.check()
        await asyncio.sleep(b.get("sleep", 0))
        if holder.stopped:
            raise Cancelled()
        staging.mkdir(parents=True, exist_ok=True)
        f = staging / f"{name}.mp4"
        f.write_bytes(b"video")
        (staging / f"{name}.jpg").write_bytes(b"\xff\xd8\xffjpg")
        on_progress(progress=1.0, downloaded=5, total=5, speed=None, eta=0)
        return {"file": f, "thumb": staging / f"{name}.jpg"}
    return dl


async def run_until(r, cond, timeout=10):
    stop = asyncio.Event()
    task = asyncio.create_task(r.run(stop))
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            break
        await asyncio.sleep(0.1)
    stop.set()
    await task


def probe_video(title):
    async def p(url, ctx):
        return {"type": "video", "method": "ytdlp", "title": title, "height": 1080, "count": 1,
                "info": {"full": True, "requested_formats": [{"format_id": "1"}], "title": title}}
    return p


def test_download_saves_video_and_jpg_in_order(rt, monkeypatch):
    order = []
    monkeypatch.setattr(runner_mod, "probe_url", lambda url, ctx: probe_video(url.split("/")[-1])(url, ctx))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: order.append(u) or {}))
    a, _ = rt.add("https://x/první")
    b, _ = rt.add("https://x/druhé")
    asyncio.run(run_until(rt, lambda: rt.db.get(b)["status"] == "done"))
    assert order == ["https://x/první", "https://x/druhé"]
    j = rt.db.get(a)
    assert j["status"] == "done" and Path(j["filepath"]).name == "první.mp4"
    assert Path(j["filepath"]).with_suffix(".jpg").exists()
    assert not rt.staging(a).exists()


def test_duplicate_url_not_added_twice(rt):
    a, new1 = rt.add("https://x/v")
    b, new2 = rt.add("https://x/v")
    assert a == b and new1 and not new2


def test_fallback_to_sniffer_and_combined_error(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: ResolveError("Unsupported URL", "unsupported")))

    async def sn_fail(*a, **k):
        raise ResolveError("na stránce nebylo nalezeno žádné video", "unsupported")
    monkeypatch.setattr(runner_mod.sniffer, "sniff", sn_fail)
    j, _ = rt.add("https://x/v")
    asyncio.run(run_until(rt, lambda: rt.db.get(j)["status"] == "failed"))
    job = rt.db.get(j)
    assert "yt-dlp: Unsupported URL" in job["error"] and "sniffer:" in job["error"]
    assert ("error", j, job["error"]) in rt.events


def test_no_fallback_for_login_error_and_no_retry(rt, monkeypatch):
    called = []
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: ResolveError("Sign in to confirm your age", "login")))

    async def sn(*a, **k):
        called.append(1)
    monkeypatch.setattr(runner_mod.sniffer, "sniff", sn)
    j, _ = rt.add("https://x/v")
    asyncio.run(run_until(rt, lambda: rt.db.get(j)["status"] == "failed"))
    assert not called and rt.db.get(j)["attempts"] == 1


def test_network_error_is_retried_later(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: ResolveError("Read timed out", "network")))
    j, _ = rt.add("https://x/v")
    asyncio.run(run_until(rt, lambda: (rt.db.get(j)["attempts"] or 0) >= 1 and rt.db.get(j)["status"] == "queued"))
    job = rt.db.get(j)
    assert job["status"] == "queued" and job["not_before"] > time.time() + 30


def test_paused_job_is_skipped_until_resumed(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", lambda url, ctx: probe_video(url)(url, ctx))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: {"sleep": 1}))
    a, _ = rt.add("https://x/a")
    b, _ = rt.add("https://x/b")

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(rt.run(stop))
        while rt.db.get(a)["status"] in ("new", "probing"):
            await asyncio.sleep(0.05)
        rt.set_paused(a, True)  # i rozběhnuté stahování se zastaví a vrátí do fronty
        t0 = time.time()
        while rt.db.get(b)["status"] != "done" and time.time() - t0 < 10:
            await asyncio.sleep(0.1)
        assert rt.db.get(a)["status"] == "queued"  # přeskočeno, stále na svém místě
        rt.set_paused(a, False)
        while rt.db.get(a)["status"] != "done" and time.time() - t0 < 10:
            await asyncio.sleep(0.1)
        stop.set()
        await task
    asyncio.run(scenario())
    assert rt.db.get(a)["status"] == "done"


def test_cancel_running_job_cleans_staging(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: {"sleep": 5}))
    j, _ = rt.add("https://x/v")

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(rt.run(stop))
        while rt.db.get(j)["status"] != "running":
            await asyncio.sleep(0.05)
        rt.staging(j).mkdir(parents=True, exist_ok=True)
        rt.cancel(j)
        t0 = time.time()
        while rt.db.get(j)["status"] != "cancelled" and time.time() - t0 < 10:
            await asyncio.sleep(0.1)
        stop.set()
        await task
    asyncio.run(scenario())
    assert rt.db.get(j)["status"] == "cancelled" and not rt.staging(j).exists()


def test_big_playlist_needs_confirmation_then_expands_with_folder(rt, monkeypatch):
    entries = [{"url": f"https://x/v{i}", "title": f"Díl {i}"} for i in range(5)]

    async def probe(url, ctx):
        return {"type": "playlist", "method": "ytdlp", "title": "Můj playlist", "count": 5, "entries": [dict(e) for e in entries], "height": 720}
    monkeypatch.setattr(runner_mod, "probe_url", probe)
    p, _ = rt.add("https://x/list")
    asyncio.run(run_until(rt, lambda: rt.db.get(p)["status"] == "confirm"))
    assert rt.db.get(p)["status"] == "confirm"
    assert rt.confirm(p)
    kids = rt.db.children(p)
    assert len(kids) == 5 and all(k["subdir"] == "Můj playlist" for k in kids)
    assert rt.db.get(p)["status"] == "expanded"


def test_playlist_failure_summary_once(rt, monkeypatch):
    rt.settings.update({"playlist_confirm_threshold": 50})

    async def probe(url, ctx):
        return {"type": "playlist", "method": "ytdlp", "title": "PL", "count": 2,
                "entries": [{"url": "https://x/ok", "title": "ok"}, {"url": "https://x/bad", "title": "bad"}]}
    monkeypatch.setattr(runner_mod, "probe_url", probe)

    async def full_info(url, ctx, timeout=180):
        return {"title": url, "requested_formats": [{"format_id": "1"}]}
    monkeypatch.setattr(runner_mod.ytdlp, "full_info", full_info)
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: ResolveError("Video unavailable", "removed") if "bad" in u else {}))
    p, _ = rt.add("https://x/list")
    asyncio.run(run_until(rt, lambda: any(e[0] == "summary" for e in rt.events)))
    summaries = [e for e in rt.events if e[0] == "summary"]
    assert summaries == [("summary", p, 1, 2)]
    assert not [e for e in rt.events if e[0] == "error"]  # u playlistu jen souhrn


def test_unavailable_target_pauses_and_resumes_queue(rt, tmp_path):
    ro = tmp_path / "nas"
    ro.mkdir()
    rt.settings.update({"download_dir": str(ro / "VidDown")})
    ro.chmod(0o500)  # „odpojený NAS“
    try:
        asyncio.run(rt._check_target(rt.settings.all()))
        assert rt.queue_paused() and rt.db.kv_get("queue_pause_reason") == "target"
    finally:
        ro.chmod(0o700)
    rt._target_checked = -1e9
    asyncio.run(rt._check_target(rt.settings.all()))
    assert not rt.queue_paused()


def test_finished_file_waits_for_target_instead_of_redownload(rt, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: calls.append(u) or {}))
    j, _ = rt.add("https://x/v")
    real_move = runner_mod.shutil.move
    state = {"fail": True}

    def flaky_move(src, dst):
        if state["fail"]:
            raise OSError(5, "Input/output error")
        return real_move(src, dst)
    monkeypatch.setattr(runner_mod.shutil, "move", flaky_move)
    asyncio.run(run_until(rt, lambda: rt.db.get(j)["error_kind"] == "target"))
    assert rt.db.get(j)["status"] == "queued" and (rt.staging(j) / runner_mod.PENDING).exists()
    state["fail"] = False
    rt.db.update(j, not_before=None)
    asyncio.run(run_until(rt, lambda: rt.db.get(j)["status"] == "done"))
    assert rt.db.get(j)["status"] == "done" and len(calls) == 1  # znovu se nestahovalo
