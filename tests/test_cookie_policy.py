"""Cookies jen když je potřeba (cookies_use = needed): pokus bez cookies, s cookies až při hlášce o přihlášení."""
import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from viddown.config import Settings
from viddown.resolvers import Ctx, ResolveError, cookiepolicy, ytdlp
from viddown.server import create_app
from tests.test_api import State

COOKIES = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t9999999999\tSID\tabc\n"


class Bin:
    def __init__(self, p): self.p = p
    def bin_path(self, *a, **k): return self.p


class Engines:
    def get(self, name):
        return Bin("/bin/yt-dlp" if name == "yt-dlp" else None)


def ctx(tmp_path, use="needed", mode="file", cookies=True, **extra):
    if cookies:
        (tmp_path / "cookies.txt").write_text(COOKIES)
    return Ctx({"cookies_mode": mode, "cookies_use": use, **extra}, Engines(), tmp_path)


def run(coro):
    return asyncio.run(coro)


class Calls:
    """Falešná metoda: zaznamená, zda šla s cookies; bez cookies vyhodí zadanou chybu."""

    def __init__(self, error=None, empty_first=False):
        self.seen, self.error, self.empty_first = [], error, empty_first

    async def __call__(self, c):
        with_ck = c.cookies_file is not None
        self.seen.append(with_ck)
        if not with_ck and self.error:
            raise self.error
        if self.empty_first:
            return {"candidates": [{"url": "x"}] if with_ck else [], "drm": False}
        return {"ok": with_ck}


def test_always_mode_sends_cookies_right_away(tmp_path):
    f = Calls()
    run(cookiepolicy.attempt(ctx(tmp_path, use="always"), "https://example.com/v", f))
    assert f.seen == [True]


def test_needed_mode_tries_without_then_with_cookies_and_learns_the_site(tmp_path):
    c = ctx(tmp_path)
    f = Calls(ResolveError("Sign in to confirm your age", "login"))
    assert run(cookiepolicy.attempt(c, "https://www.example.com/v1", f)) == {"ok": True}
    assert f.seen == [False, True]
    assert "example.com" in cookiepolicy.learned(tmp_path)
    g = Calls(ResolveError("Sign in to confirm your age", "login"))
    run(cookiepolicy.attempt(c, "https://example.com/v2", g))
    assert g.seen == [True]                               # naučený web: rovnou s cookies, bez dvojího pokusu


def test_needed_mode_without_login_error_never_uses_cookies(tmp_path):
    f = Calls()
    assert run(cookiepolicy.attempt(ctx(tmp_path), "https://example.com/v", f)) == {"ok": False}
    assert f.seen == [False]
    assert cookiepolicy.learned(tmp_path) == {}


@pytest.mark.parametrize("err", [
    ResolveError("HTTP Error 429: Too Many Requests. Sign in", "login"),   # omezení webu se neřeší cookies
    ResolveError("Connection reset", "network"),
    ResolveError("Unsupported URL", "unsupported"),
])
def test_rate_limit_and_other_errors_do_not_retry_with_cookies(tmp_path, err):
    f = Calls(err)
    with pytest.raises(ResolveError):
        run(cookiepolicy.attempt(ctx(tmp_path), "https://example.com/v", f))
    assert f.seen == [False]


def test_failed_retry_with_cookies_is_not_learned(tmp_path):
    async def always_login(c):
        raise ResolveError("Private video. Sign in", "login")
    with pytest.raises(ResolveError):
        run(cookiepolicy.attempt(ctx(tmp_path), "https://example.com/v", always_login))
    assert cookiepolicy.learned(tmp_path) == {}


def test_no_cookies_configured_means_single_attempt(tmp_path):
    f = Calls(ResolveError("Sign in", "login"))
    with pytest.raises(ResolveError):
        run(cookiepolicy.attempt(ctx(tmp_path, mode="none"), "https://example.com/v", f))
    assert f.seen == [False]


def test_sites_always_with_cookies(tmp_path):
    c = ctx(tmp_path, cookies_always_hosts="www.example.com, https://other.org/x")
    f = Calls()
    run(cookiepolicy.attempt(c, "https://m.example.com/v", f))
    run(cookiepolicy.attempt(c, "https://other.org/v", f))
    run(cookiepolicy.attempt(c, "https://third.net/v", f))
    assert f.seen == [True, True, False]


def test_learned_site_expires(tmp_path):
    (tmp_path / cookiepolicy.FILE).write_text(json.dumps({"example.com": time.time() - 1, "b.com": time.time() + 99}))
    assert list(cookiepolicy.learned(tmp_path)) == ["b.com"]
    cookiepolicy.forget(tmp_path, "b.com")
    assert cookiepolicy.learned(tmp_path) == {}


def test_youtube_addresses_share_one_learned_site(tmp_path):
    c = ctx(tmp_path)
    cookiepolicy.learn(tmp_path, "https://youtu.be/abc")
    f = Calls()
    run(cookiepolicy.attempt(c, "https://www.youtube.com/watch?v=x", f))
    assert f.seen == [True]


def test_nested_call_keeps_the_decision(tmp_path):
    c = cookiepolicy.without_cookies(ctx(tmp_path))
    f = Calls(ResolveError("Sign in", "login"))
    with pytest.raises(ResolveError):
        run(cookiepolicy.attempt(c, "https://example.com/v", f))
    assert f.seen == [False]


def test_sniffer_empty_page_retries_with_cookies_only_if_file_has_the_site(tmp_path):
    empty = lambda sn: not sn["candidates"]
    f = Calls(empty_first=True)
    sn = run(cookiepolicy.attempt(ctx(tmp_path), "https://www.example.com/v", f, empty=empty))
    assert f.seen == [False, True] and sn["candidates"]
    assert "example.com" in cookiepolicy.learned(tmp_path)
    g = Calls(empty_first=True)
    sn = run(cookiepolicy.attempt(ctx(tmp_path), "https://unrelated.net/v", g, empty=empty))
    assert g.seen == [False] and not sn["candidates"]      # cookies.txt k tomuto webu nic nemá


def test_ctx_and_ytdlp_command_follow_the_decision(tmp_path):
    c = ctx(tmp_path)
    assert cookiepolicy.without_cookies(c).cookies_file is None
    assert cookiepolicy.with_cookies(c).cookies_file == tmp_path / "cookies.txt"
    assert "--cookies" not in ytdlp.base_cmd(cookiepolicy.without_cookies(c))
    assert "--cookies" in ytdlp.base_cmd(cookiepolicy.with_cookies(c))
    b = ctx(tmp_path, mode="browser", cookies=False)
    assert "--cookies-from-browser" not in ytdlp.base_cmd(cookiepolicy.without_cookies(b))
    assert "--cookies-from-browser" in ytdlp.base_cmd(cookiepolicy.with_cookies(b))


def test_ytdlp_probe_retries_with_cookies(tmp_path, monkeypatch):
    cmds = []

    async def fake_run(cmd, timeout, ctx=None, ck=None):
        cmds.append(cmd)
        ytdlp._drop(ck)
        if "--cookies" not in cmd:
            raise ResolveError("Sign in to confirm you're not a bot", "login")
        return {"id": "x"}

    monkeypatch.setattr(ytdlp, "_run_json", fake_run)
    assert run(ytdlp.probe("https://www.youtube.com/watch?v=x", ctx(tmp_path))) == {"id": "x"}
    assert ["--cookies" in c for c in cmds] == [False, True]
    cmds.clear()
    run(ytdlp.full_info("https://youtu.be/y", ctx(tmp_path)))
    assert ["--cookies" in c for c in cmds] == [True]       # YouTube už je naučený


def test_stale_cookie_hint_only_after_attempt_with_cookies(tmp_path):
    c = ctx(tmp_path)
    msg = "[youtube] x: Sign in to confirm your age"
    assert ytdlp.COOKIES_STALE not in ytdlp.cookie_hint(msg, cookiepolicy.without_cookies(c))
    assert ytdlp.COOKIES_STALE in ytdlp.cookie_hint(msg, cookiepolicy.with_cookies(c))


def test_settings_validate_and_normalize(data):
    s = Settings()
    assert s.get("cookies_use") == "always"
    s.update({"cookies_use": "needed", "cookies_always_hosts": " https://www.Example.com/x ;b.org  b.org "})
    assert s.get("cookies_always_hosts") == "example.com, b.org"
    with pytest.raises(ValueError):
        s.update({"cookies_use": "sometimes"})


def test_api_lists_and_forgets_learned_sites(data, tmp_path):
    st = State(data)
    st.settings.update({"download_dir": str(tmp_path)})
    cookiepolicy.learn(st.data, "https://example.com/v")
    cookiepolicy.learn(st.data, "https://b.org/v")
    c = TestClient(create_app(st))
    hosts = [x["host"] for x in c.get("/api/settings").json()["cookie_hosts"]]
    assert hosts == ["b.org", "example.com"]
    r = c.delete("/api/settings/cookie-hosts", params={"host": "example.com"})
    assert [x["host"] for x in r.json()["cookie_hosts"]] == ["b.org"]


def test_gui_has_the_setting_and_help():
    js = (Path(__file__).parents[1] / "src/viddown/web/app.js").read_text()
    assert "cookieUseHtml" in js and 'data-k="cookies_use"' in js and "cookies_always_hosts" in js
    assert "/api/settings/cookie-hosts" in js and "Jen když je potřeba" in js and "Only when needed" in js
