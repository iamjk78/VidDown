"""Deep review (dávka 2): ztráta hotového videa, přesun na NAS, blokování smyčky, rozbalení playlistu, pořadí ve frontě."""
import asyncio
import errno
import json
import shutil
import time

import pytest

from tests.test_runner import rt, run_until  # noqa: F401
from viddown import runner as runner_mod
from viddown.resolvers import ResolveError, ytdlp


def make_job(rt, name="Video"):
    jid = rt.db.add("https://x/v", status="queued", kind="video")
    staging = rt.staging(jid)
    staging.mkdir(parents=True, exist_ok=True)
    f = staging / f"{name}.mp4"
    f.write_bytes(b"x" * 100)
    return jid, staging, f


# --- hotové video přežije přerušení po zápisu do archivu ------------------------------------------------
def test_finished_file_with_pending_marker_is_only_moved_not_downloaded_again(rt, monkeypatch):
    jid, staging, f = make_job(rt)
    ytdlp.save_pending(staging, f, None, "log", "ytdlp")
    assert json.loads((staging / ytdlp.PENDING).read_text())["file"] == str(f)

    async def boom(*a, **kw):
        raise AssertionError("yt-dlp se nesmí spustit znovu (archiv by označil video za už stažené a smazal ho)")
    monkeypatch.setattr(runner_mod.ytdlp, "download", boom)
    asyncio.run(run_until(rt, lambda: rt.db.get(jid)["status"] == "done"))
    j = rt.db.get(jid)
    assert j["status"] == "done" and j["filepath"] and open(j["filepath"], "rb").read() == b"x" * 100
    assert not staging.exists()


def test_save_pending_ignores_unwritable_staging(tmp_path):
    ytdlp.save_pending(tmp_path / "neexistuje" / "a", tmp_path / "f.mp4", None, "")        # nesmí vyhodit výjimku


# --- přesun do cíle ----------------------------------------------------------------------------------------
def result_for(f):
    return {"file": f, "thumb": None, "log": "log"}


def test_failed_copy_leaves_no_half_file_in_target_and_keeps_the_download(rt, monkeypatch, tmp_path):
    jid, staging, f = make_job(rt)
    target = tmp_path / "dl"
    real_move = shutil.move

    def half_copy(src, dst):
        open(dst, "wb").write(b"x" * 10)                              # poloviční kopie
        raise OSError(errno.EIO, "výpadek NAS")
    monkeypatch.setattr(runner_mod.shutil, "move", half_copy)
    with pytest.raises(ResolveError) as e:
        rt._finalize(jid, result_for(f), "ytdlp", staging)
    assert e.value.kind == "target"
    assert f.exists() and (staging / ytdlp.PENDING).exists()           # video zůstává ke zopakování
    assert [p.name for p in target.rglob("*") if p.is_file()] == []    # v cíli není nic, ani poloviční soubor
    monkeypatch.setattr(runner_mod.shutil, "move", real_move)
    rt._finalize(jid, result_for(f), "ytdlp", staging)                 # po obnovení cíle se dokončí
    assert rt.db.get(jid)["status"] == "done" and open(rt.db.get(jid)["filepath"], "rb").read() == b"x" * 100


def test_full_target_pauses_the_queue_with_disk_reason(rt, monkeypatch):
    jid, staging, f = make_job(rt)

    def full(src, dst):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(runner_mod.shutil, "move", full)
    with pytest.raises(ResolveError) as e:
        rt._finalize(jid, result_for(f), "ytdlp", staging)
    assert e.value.kind == "disk" and rt.queue_paused() and rt.db.kv_get("queue_pause_reason") == "disk"
    rt._failed(jid, "plno", "disk", staging)
    assert rt.db.get(jid)["status"] == "queued" and f.exists()


def test_persistent_target_error_fails_after_five_tries_but_keeps_the_video(rt):
    jid, staging, f = make_job(rt)
    for i in range(4):
        rt._failed(jid, "Cílová složka není dostupná", "target", staging)
        assert rt.db.get(jid)["status"] == "queued"
    rt._failed(jid, "Cílová složka není dostupná", "target", staging)
    j = rt.db.get(jid)
    assert j["status"] == "failed" and str(staging) in j["error"] and f.exists()          # video se nesmaže


def test_target_errors_while_queue_is_paused_are_not_counted(rt):
    jid, staging, f = make_job(rt)
    rt.db.kv_set("queue_paused", True)
    for i in range(10):
        rt._failed(jid, "NAS odpojen", "target", staging)
    assert rt.db.get(jid)["status"] == "queued"


# --- zaseknutý disk nezastaví aplikaci --------------------------------------------------------------------
def test_stuck_disk_status_does_not_block_and_falls_back_to_last_known(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "DISK_TIMEOUT", 0.2)
    first = asyncio.run(rt.disk_status_async())
    assert "temp_free" in first
    calls = []

    def stuck(s=None):
        calls.append(1)
        time.sleep(1.5)
        return {"low": "target"}
    monkeypatch.setattr(rt, "disk_status", stuck)
    rt._disk_cache = (-1e9, first)

    async def go():
        t0 = time.monotonic()
        r = await rt.disk_status_async()
        return r, time.monotonic() - t0
    r, took = asyncio.run(go())
    assert r == first and took < 1.0                                   # vrátil poslední známý stav a nečekal na zaseknutý disk


# --- rozbalení playlistu ----------------------------------------------------------------------------------
def test_expand_failure_marks_the_playlist_failed_instead_of_losing_it(rt, monkeypatch):
    jid = rt.db.add("https://x/list", status="probing")

    def boom(job, entries=None):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(rt, "_expand", boom)
    rt.apply_probe(rt.db.get(jid), {"type": "playlist", "method": "ytdlp", "title": "P", "count": 1, "entries": [{"url": "https://x/a"}]})
    j = rt.db.get(jid)
    assert j["status"] == "failed" and "database is locked" in j["error"]


def test_playlist_is_not_marked_expanded_before_its_children_exist(rt):
    jid = rt.db.add("https://x/list", status="probing")
    seen = {}
    real = rt._expand

    def spy(job, entries=None):
        seen["status_before"] = rt.db.get(job["id"])["status"]
        return real(job, entries)
    rt._expand = spy
    rt.apply_probe(rt.db.get(jid), {"type": "playlist", "method": "ytdlp", "title": "P", "count": 2, "entries": [{"url": "https://x/a"}, {"url": "https://x/b"}]})
    assert seen["status_before"] == "probing" and rt.db.get(jid)["status"] == "expanded" and len(rt.db.children(jid)) == 2


def test_playlist_with_only_duplicates_is_skipped_not_left_expanded_without_children(rt):
    rt.db.add("https://x/a", status="queued")
    jid = rt.db.add("https://x/list", status="probing")
    rt.apply_probe(rt.db.get(jid), {"type": "playlist", "method": "ytdlp", "title": "P", "count": 1, "entries": [{"url": "https://x/a"}]})
    assert rt.db.get(jid)["status"] == "skipped" and not rt.db.children(jid)


# --- pořadí ve frontě --------------------------------------------------------------------------------------
def test_moving_a_playlist_keeps_its_videos_together_before_the_target(data):
    from viddown.db import DB
    db = DB(data / "t.db")
    p = db.add("https://p", status="expanded", kind="playlist")
    db.add_children(p, [{"url": f"https://p/{i}"} for i in range(30)], None, "gui")
    q = db.add("https://q", status="expanded", kind="playlist")
    qk = db.add_children(q, [{"url": f"https://q/{i}"} for i in range(50)], None, "gui")
    db.move(p, qk[5])                                                    # před šesté video druhého playlistu
    urls = [j["url"] for j in db.queue()]
    i_q = urls.index("https://q/5")
    assert urls[i_q - 31:i_q] == ["https://p"] + [f"https://p/{i}" for i in range(30)]          # celý playlist těsně před cílem
    assert urls.count("https://p/3") == 1 and urls.index("https://q/4") == i_q - 32


def test_repeated_moves_never_collapse_positions(data):
    from viddown.db import DB
    db = DB(data / "t.db")
    a = db.add("https://a", status="queued")
    b = db.add("https://b", status="queued")
    c = db.add("https://c", status="queued")
    for i in range(80):                                                  # opakované půlení mezery
        db.move(c, b) if i % 2 == 0 else db.move(c, a)
    pos = [j["pos"] for j in db.queue()]
    assert len(set(pos)) == len(pos) == 3 and pos == sorted(pos)
    assert [j["url"] for j in db.queue()][0] == "https://c"
