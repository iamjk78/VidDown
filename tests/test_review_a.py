"""Dávka A po hloubkové revizi: ztráta hotových videí, souběžné přesuny, zrušené úlohy, chyby katalogu a odběrů."""
import asyncio
import json
import os
import stat
from pathlib import Path

from viddown import runner as runner_mod
from viddown import util
from viddown.config import DEFAULTS
from viddown.resolvers import Cancelled, Ctx, ProcHolder, ytdlp
from test_runner import rt, fake_download, probe_video, run_until  # noqa: F401


def test_interrupted_remux_keeps_finished_video_for_later(tmp_path, monkeypatch):
    staging = tmp_path / "stg"
    staging.mkdir()
    video = staging / "v.mkv"
    video.write_bytes(b"x")
    exe = tmp_path / "fake-ytdlp"
    exe.write_text(f"#!/bin/sh\necho 'VDFILE {video}'\nexit 0\n")
    exe.chmod(stat.S_IRWXU)

    class B:
        def __init__(self, p): self.p = p
        def bin_path(self): return self.p

    class E:
        def get(self, n): return B(str(exe) if n == "yt-dlp" else None)

    async def cancelled(*a, **k):
        raise Cancelled()
    monkeypatch.setattr(ytdlp.container, "remux_mkv_to_mp4", cancelled)
    ctx = Ctx({**DEFAULTS, "cookies_mode": "none", "mkv_to_mp4": True}, E(), tmp_path)
    try:
        asyncio.run(ytdlp.download("https://x/v", None, ctx, staging, "v", None, lambda **k: None, ProcHolder()))
        raised = False
    except Cancelled:
        raised = True
    assert raised
    d = json.loads((staging / ytdlp.PENDING).read_text())
    assert Path(d["file"]) == video and video.exists()


def test_unique_target_respects_partial_files_of_other_moves(tmp_path):
    (tmp_path / "v.mp4.viddown-part").write_bytes(b"x")
    assert util.unique_target(tmp_path, "v", ".mp4").name == "v (2).mp4"


def test_concurrent_places_with_same_name_do_not_overwrite(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    ids = [rt.add(f"https://x/{i}")[0] for i in range(2)]
    results = []
    for i, jid in enumerate(ids):
        st = rt.staging(jid)
        st.mkdir(parents=True, exist_ok=True)
        f = st / "same.mp4"
        f.write_bytes(f"video{i}".encode())
        results.append((jid, {"file": f, "thumb": None, "log": ""}))
    dests = [rt._place(jid, r, "ytdlp", rt.staging(jid)) for jid, r in results]
    assert dests[0] != dests[1] and {d.read_bytes() for d in dests} == {b"video0", b"video1"}
    assert not list(dests[0].parent.glob("*.viddown-part"))


def test_failed_move_keeps_video_and_retry_adopts_it(rt):
    jid, _ = rt.add("https://x/v")
    st = rt.staging(jid)
    st.mkdir(parents=True, exist_ok=True)
    f = st / "v.mp4"
    f.write_bytes(b"video")
    ytdlp.save_pending(st, f, None, "log")
    rt.db.update(jid, status="failed", error_kind="target")
    rt._finish_cancelling()                                           # úklid při startu hotové video nesmaže
    assert f.exists()
    new = rt.retry(jid)
    ns = rt.staging(new)
    assert not st.exists() and (ns / "v.mp4").exists()
    assert json.loads((ns / ytdlp.PENDING).read_text())["file"] == str(ns / "v.mp4")


def test_error_after_cancel_does_not_resurrect_job(rt):
    jid, _ = rt.add("https://x/v")
    rt.db.update(jid, status="cancelling")
    rt._failed(jid, "boom", "other", rt.staging(jid))
    assert rt.db.get(jid)["status"] == "cancelled"


def test_exception_before_try_frees_the_slot(rt):
    async def go():
        rt.running[999] = (None, None)
        await rt._execute(999, ProcHolder())
    asyncio.run(go())
    assert 999 not in rt.running


def test_rate_limit_regex_ignores_numbers_in_urls_and_ids():
    assert util.is_rate_limited("HTTP Error 429: Too Many Requests")
    assert util.is_rate_limited("The current session has been rate-limited by YouTube for up to an hour")
    assert not util.is_rate_limited("Unable to download https://x.example/video/429/index.m3u8")
    assert not util.is_rate_limited("[youtube] abc429xyz: failed")
