"""Dávka F po hloubkové revizi: pauza webu po omezení je společná pro stahování, kontrolu URL, náhledy, odběry a katalog;
kontrola URL se po omezení nebo výpadku spojení zopakuje; odběry nepřidávají videa, která už ve frontě jsou."""
import asyncio
import time
from types import SimpleNamespace

from tests.test_runner import rt, run_until  # noqa: F401
from viddown import catalogdetails as cd
from viddown import runner as runner_mod
from viddown import subscriptions


def test_url_check_waits_while_the_site_is_paused(rt, monkeypatch):
    calls = []

    async def probe(url, ctx):
        calls.append(url)
        return {"type": "none", "error": "x", "error_kind": "other"}
    monkeypatch.setattr(runner_mod, "probe_url", probe)
    rt.note_host_limit("https://www.youtube.com/watch?v=a", "HTTP Error 429")
    a, _ = rt.add("https://youtu.be/abc")
    b, _ = rt.add("https://x.example/v")
    asyncio.run(run_until(rt, lambda: rt.db.get(b)["status"] == "failed", timeout=5))
    assert calls == ["https://x.example/v"] and rt.db.get(a)["status"] == "new"          # YouTube počká, jiný web běží dál


def test_rate_limited_url_check_is_retried_later_and_pauses_the_site(rt, monkeypatch):
    async def probe(url, ctx):
        return {"type": "none", "error": "The current session has been rate-limited by YouTube", "error_kind": "other"}
    monkeypatch.setattr(runner_mod, "probe_url", probe)
    a, _ = rt.add("https://youtu.be/abc")
    asyncio.run(run_until(rt, lambda: rt.db.get(a)["error_kind"] == "ratelimit", timeout=5))
    j = rt.db.get(a)
    assert j["status"] == "new" and j["not_before"] > time.time() + 600 and rt.host_paused_until("youtube.com")


def test_network_error_in_url_check_is_retried_then_fails(rt, monkeypatch):
    rt.settings.update({"auto_retry_attempts": 1})
    monkeypatch.setattr(runner_mod, "RETRY_DELAYS", [0, 0, 0])
    calls = []

    async def probe(url, ctx):
        calls.append(url)
        return {"type": "none", "error": "Connection reset by peer", "error_kind": "network"}
    monkeypatch.setattr(runner_mod, "probe_url", probe)
    a, _ = rt.add("https://x.example/v")
    asyncio.run(run_until(rt, lambda: rt.db.get(a)["status"] == "failed", timeout=8))
    assert len(calls) == 2                                                     # jednou znovu, pak teprve „selhalo“


def test_due_subscription_skips_paused_sites(rt):
    s1 = rt.db.sub_add("https://www.youtube.com/@a", "/tmp/a", kind="channel")
    s2 = rt.db.sub_add("https://x.example/feed", "/tmp/b", kind="playlist")
    rt.note_host_limit("youtube.com", "429")
    got = subscriptions.due(rt.db, 6, skip=rt.host_paused_until)
    assert got is not None and got["id"] == s2 and s1 != s2


def test_subscription_does_not_queue_videos_already_in_the_queue(rt):
    rt.add("https://x.example/v1")
    sid = rt.db.sub_add("https://x.example/feed", "/tmp/b", kind="playlist")
    n = subscriptions.queue_entries(rt.db, rt.db.sub_get(sid), [{"url": "https://x.example/v1"}, {"url": "https://x.example/v2"},
                                                                   {"url": "https://x.example/v2"}])
    assert n == 1 and len(rt.db.query("select 1 from jobs where url='https://x.example/v2'")) == 1


def test_catalog_shares_the_site_pause_with_the_queue(rt):
    st = SimpleNamespace(data=rt.data, settings=rt.settings, db=rt.db, runner=rt)
    w = cd.DetailWorker(st)
    w._on_error({"host": "www.youtube.com", "id": 1}, "other", "rate-limited by YouTube, try again later")
    assert rt.host_paused_until("youtube.com")                                 # fronta i odběry YouTube pozastavily také
    rt.host_pause.clear()
    rt.note_host_limit("youtube.com", "429 z fronty")
    w._known_hosts = lambda: {"www.youtube.com", "x.example"}
    assert "www.youtube.com" in w.limited_hosts() and "x.example" not in w.limited_hosts()
