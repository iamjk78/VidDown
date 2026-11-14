"""Neplatné YouTube cookies: příznak, jednorázové upozornění za 24 h, zhasnutí po nahrání nebo po stažení věkově omezeného videa."""
import asyncio

from tests.test_runner import fake_download, probe_video, rt, run_until  # noqa: F401
from viddown import runner as runner_mod
from viddown.resolvers import ResolveError
from viddown.resolvers.ytdlp import COOKIES_STALE

STALE = f"[youtube] a: Sign in to confirm your age. {COOKIES_STALE}: exportujte je znovu."


def collect(rt):
    notes = []

    class L:
        def on_notice(self, kind, **kw): notes.append(kind)
    rt.listeners.append(L())
    return notes


def fail_one(rt, monkeypatch, url, msg):
    rt.settings.update({"sleep_youtube_min": 0, "sleep_youtube_max": 0})
    monkeypatch.setattr(runner_mod, "probe_url", probe_video("V"))
    monkeypatch.setattr(runner_mod.ytdlp, "download", fake_download(lambda u: ResolveError(msg, "login")))
    j, _ = rt.add(url)
    asyncio.run(run_until(rt, lambda: rt.db.get(j)["status"] == "failed", timeout=15))
    assert rt.db.get(j)["status"] == "failed"
    return j


def test_stale_cookie_failure_sets_flag_and_notifies_once_a_day(rt, monkeypatch):
    notes = collect(rt)
    fail_one(rt, monkeypatch, "https://www.youtube.com/watch?v=aaaaaaaaaaa", STALE)
    assert rt.db.kv_get("yt_cookies_bad") and notes.count("yt_cookies") == 1
    fail_one(rt, monkeypatch, "https://www.youtube.com/watch?v=bbbbbbbbbbb", STALE)
    assert notes.count("yt_cookies") == 1                                                      # druhé selhání už neupozorní
    rt.db.kv_set("yt_cookies_notice_at", 1.0)                                                  # uplynulo víc než 24 hodin
    fail_one(rt, monkeypatch, "https://www.youtube.com/watch?v=ccccccccccc", STALE)
    assert notes.count("yt_cookies") == 2


def test_other_login_errors_do_not_set_the_flag(rt, monkeypatch):
    notes = collect(rt)
    fail_one(rt, monkeypatch, "https://www.youtube.com/watch?v=aaaaaaaaaaa", "[youtube] a: Private video. Sign in if you've been granted access")
    assert not rt.db.kv_get("yt_cookies_bad") and "yt_cookies" not in notes


def test_flag_clears_only_after_an_age_restricted_youtube_download(rt):
    rt.db.kv_set("yt_cookies_bad", 1.0)
    rt._yt_cookies_ok({"url": "https://x.example/a", "info": '{"age_limit": 18}'})            # jiný web nic nedokazuje
    rt._yt_cookies_ok({"url": "https://youtu.be/aaaaaaaaaaa", "info": '{"age_limit": 0}'})      # běžné video také ne
    assert rt.db.kv_get("yt_cookies_bad")
    rt._yt_cookies_ok({"url": "https://youtu.be/aaaaaaaaaaa", "info": '{"age_limit": 18}'})
    assert not rt.db.kv_get("yt_cookies_bad")
