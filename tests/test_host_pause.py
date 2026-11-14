"""Pauza mezi stahováním pro každý web (u YouTube delší) a pozastavení webu po omezení dotazů."""
import asyncio
import time

import pytest

from tests.test_runner import fake_download, probe_video, rt, run_until  # noqa: F401
from viddown import runner as runner_mod
from viddown.resolvers import ResolveError
from viddown.util import host_key, is_rate_limited

YT_LIMIT = ("ERROR: [youtube] dMswPzbOmLc: This content isn't available, try again later. The current session has been "
            "rate-limited by YouTube for up to an hour. It is recommended to use `-t sleep` to add a delay between video requests")


def test_host_key_groups_all_youtube_addresses_and_ignores_ports_and_www():
    assert {host_key(u) for u in ("https://www.youtube.com/watch?v=a", "https://youtu.be/a", "https://m.youtube.com/watch?v=b",
                                  "https://music.youtube.com/watch?v=c")} == {"youtube.com"}
    assert host_key("https://www.example.com:8080/x") == "example.com" and host_key("") == ""


def test_rate_limit_detection():
    assert is_rate_limited(YT_LIMIT) and is_rate_limited("HTTP Error 429: Too Many Requests") and is_rate_limited("rate limit exceeded")
    assert not is_rate_limited("Video unavailable") and not is_rate_limited("Sign in to confirm you're not a bot") and not is_rate_limited("HTTP Error 403")


def test_sleep_range_is_longer_for_youtube_and_follows_the_settings():
    s = {"sleep_min": 5, "sleep_max": 15, "sleep_youtube_min": 30, "sleep_youtube_max": 60}
    assert all(30 <= runner_mod.Runner._sleep_for("youtube.com", s) <= 60 for _ in range(50))
    assert all(5 <= runner_mod.Runner._sleep_for("example.com", s) <= 15 for _ in range(50))
    assert runner_mod.Runner._sleep_for("youtube.com", {"sleep_youtube_min": 9, "sleep_youtube_max": 3}) == 9      # max pod min = min


def run_two(rt, monkeypatch, urls, pause):
    rt.settings.update({"sleep_min": pause, "sleep_max": pause, "playlist_confirm_threshold": 50})
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    starts, ends = {}, {}
    real = fake_download(lambda u: {})

    async def dl(url, info, ctx, staging, name, rate, on_progress, holder, audio_only=None):
        starts[url] = time.monotonic()
        res = await real(url, info, ctx, staging, name, rate, on_progress, holder, audio_only)
        ends[url] = time.monotonic()
        return res
    monkeypatch.setattr(runner_mod.ytdlp, "download", dl)
    monkeypatch.setattr(runner_mod.thumbs, "final_jpg", lambda *a, **k: True)
    ids = [rt.add(u)[0] for u in urls]
    asyncio.run(run_until(rt, lambda: all(rt.db.get(i)["status"] == "done" for i in ids), timeout=20))
    return starts, ends


def test_standalone_videos_from_the_same_site_wait_between_downloads(rt, monkeypatch):
    starts, ends = run_two(rt, monkeypatch, ["https://x.example/a", "https://x.example/b"], 0.6)
    first, second = sorted(starts, key=starts.get)
    assert starts[second] - ends[first] >= 0.35                                    # pauza se počítá i od konce prvního videa, ne jen od jeho začátku


def test_different_sites_do_not_wait_for_each_other(rt, monkeypatch):
    rt.settings.update({"concurrency": 2})
    starts, ends = run_two(rt, monkeypatch, ["https://x.example/a", "https://y.example/b"], 5)
    assert abs(starts["https://x.example/a"] - starts["https://y.example/b"]) < 3


# --- omezení ze strany webu ------------------------------------------------------------------------------------
def test_rate_limit_pauses_the_whole_site_without_counting_an_attempt(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    err = ResolveError(YT_LIMIT, "other")
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: err if "youtu" in u else {}))
    monkeypatch.setattr(runner_mod.thumbs, "final_jpg", lambda *a, **k: True)
    a, _ = rt.add("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    b, _ = rt.add("https://youtu.be/bbbbbbbbbbb")
    other, _ = rt.add("https://x.example/c")
    asyncio.run(run_until(rt, lambda: rt.db.get(other)["status"] == "done" and rt.db.get(a)["error_kind"] == "ratelimit", timeout=15))
    ja, jb = rt.db.get(a), rt.db.get(b)
    assert ja["status"] == "queued" and ja["attempts"] in (0, None) and ja["not_before"] > time.time() + 800      # 15 minut, pokus se nepočítá
    assert jb["status"] == "queued" and jb["error_kind"] != "ratelimit"                                         # druhé video ani nezačalo
    assert rt.db.get(other)["status"] == "done"                                                                 # jiný web běží dál
    pauses = rt.host_pauses()
    assert [p["host"] for p in pauses] == ["youtube.com"] and 800 < pauses[0]["until"] - time.time() <= 900


def test_repeated_rate_limit_escalates_15_30_60_minutes_and_success_resets(rt):
    j = rt.db.add("https://youtu.be/aaaaaaaaaaa", status="running", kind="video")
    delays = []
    for _ in range(4):
        if "youtube.com" in rt.host_pause:
            rt.host_pause["youtube.com"]["until"] = 0                                         # předchozí pauza vypršela
        rt._rate_limited(rt.db.get(j), YT_LIMIT)
        delays.append(round(rt.host_pause["youtube.com"]["delay"]))
    assert delays == [900, 1800, 3600, 3600]
    rt._rate_limited(rt.db.get(j), YT_LIMIT)                                                    # souběžné selhání v době pauzy nezvyšuje odklad
    assert rt.host_pause["youtube.com"]["n"] == 4
    rt.host_pause.pop("youtube.com")
    rt._rate_limited(rt.db.get(j), YT_LIMIT)
    assert rt.host_pause["youtube.com"]["delay"] == 900


def test_paused_site_does_not_block_other_sites_even_with_hundreds_of_queued_videos(rt, monkeypatch):
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: {}))
    monkeypatch.setattr(runner_mod.thumbs, "final_jpg", lambda *a, **k: True)
    rt.host_pause["youtube.com"] = {"until": time.time() + 600, "delay": 900, "n": 1, "reason": "x"}
    for i in range(250):                                                                       # víc než jedna stránka dotazu ve frontě
        rt.db.add(f"https://youtu.be/v{i:010d}", status="queued", kind="video")
    other = rt.db.add("https://x.example/z", status="queued", kind="video")
    rt.db.update(other, info={"full": True, "requested_formats": [{"format_id": "1"}]})        # bez toho by se zjišťovaly podrobnosti skutečným yt-dlp
    asyncio.run(run_until(rt, lambda: rt.db.get(other)["status"] == "done", timeout=15))
    assert rt.db.get(other)["status"] == "done"


def test_state_exposes_host_pauses(rt):
    rt.host_pause["youtube.com"] = {"until": time.time() + 600, "delay": 900, "n": 1, "reason": "limit"}
    assert rt.host_pauses()[0]["host"] == "youtube.com"
    rt.host_pause["youtube.com"]["until"] = time.time() - 1
    assert rt.host_pauses() == []
