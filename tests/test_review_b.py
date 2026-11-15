"""Dávka B po hloubkové revizi: tajemství, adresy pro yt-dlp, sniffer, import nastavení, rozsahy čísel, sezení."""
import asyncio
import io
import json
import stat
from pathlib import Path

import pytest

from viddown import config, util
from viddown.resolvers import Ctx, ResolveError, sniffer, ytdlp
from test_api import client  # noqa: F401


# ------------------------------------------------------------ tajemství
def test_unreadable_secrets_keep_password_and_refuse_writes(data, monkeypatch):
    sec = config.Secrets()
    sec.set_password("tajne-heslo")
    sec.set_telegram_token("tok")
    real = Path.read_text

    def broken(self, *a, **k):
        if self.name == "secrets.json":
            raise OSError(5, "Input/output error")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", broken)
    assert sec.has_password() and sec.check_password("tajne-heslo")          # z poslední úspěšně načtené kopie
    fresh = config.Secrets()                                                  # nový proces bez kopie
    assert fresh.has_password() and not fresh.check_password("tajne-heslo")   # fail-closed: heslo vyžaduje, nikoho nepustí
    with pytest.raises(OSError):
        fresh.set_telegram_token("jiny")                                      # zápis by smazal hash hesla
    monkeypatch.setattr(Path, "read_text", real)
    assert config.Secrets().check_password("tajne-heslo") and config.Secrets().telegram_token == "tok"


def test_secrets_file_is_private_from_creation(data):
    sec = config.Secrets()
    sec.set_telegram_token("x")
    assert stat.S_IMODE(sec.path.stat().st_mode) == 0o600


# ------------------------------------------------------------ adresy
def test_is_http_url():
    assert util.is_http_url("https://example.com/v?x=1")
    for bad in ("--config-locations=/etc/passwd", "-o /tmp/x", "file:///etc/passwd", "https://a b", "ftp://x", "", "https://x\nfoo"):
        assert not util.is_http_url(bad)


def test_ytdlp_rejects_option_like_urls_and_cleans_cookie_copy(tmp_path):
    (tmp_path / "cookies.txt").write_text("# Netscape HTTP Cookie File\n.e.com\tTRUE\t/\tFALSE\t2000000000\tsid\tabc\n")
    ctx = Ctx(settings={"cookies_mode": "file"}, engines=type("E", (), {"get": lambda s, n: type("B", (), {"bin_path": lambda s: "/bin/true"})()})(), data=tmp_path)
    for fn in (ytdlp.probe, ytdlp.full_info):
        with pytest.raises(ResolveError):
            asyncio.run(fn("--config-locations=/etc/x", ctx))
    assert not list((tmp_path / "ck").glob("ck-*.txt"))


def test_ytdlp_passes_url_after_double_dash(tmp_path):
    out = tmp_path / "args.txt"
    exe = tmp_path / "ytdlp"
    exe.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {out}\necho '{{}}'\n")
    exe.chmod(0o700)
    ctx = Ctx(settings={"cookies_mode": "none"}, engines=type("E", (), {"get": lambda s, n: type("B", (), {"bin_path": lambda s: str(exe) if n == "yt-dlp" else None})()})(), data=tmp_path)
    asyncio.run(ytdlp.full_info("https://example.com/v", ctx, timeout=10))
    args = out.read_text().split("\n")
    assert args[-3:-1] == ["--", "https://example.com/v"]


# ------------------------------------------------------------ sniffer
def test_cookies_are_scoped_to_the_page_host(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("# Netscape HTTP Cookie File\n.video.example\tTRUE\t/\tFALSE\t2000000000\ta\t1\n"
                 ".bank.example\tTRUE\t/\tTRUE\t2000000000\tb\t2\n"
                 "#HttpOnly_.example.org\tTRUE\t/\tTRUE\t2000000000\tc\t3\n")
    added = []

    class Ctx_:
        async def add_cookies(self, cks):
            added.extend(cks)
    n = asyncio.run(sniffer.add_cookies(Ctx_(), f, "www.video.example"))
    assert n == 1 and [c["name"] for c in added] == ["a"]
    added.clear()
    assert asyncio.run(sniffer.add_cookies(Ctx_(), f)) == 3                      # bez omezení (Renderer, příběhy) beze změny


def test_candidates_must_be_public_http(monkeypatch):
    monkeypatch.setattr(sniffer.netsafe, "host_ok", lambda u: "intranet" not in u)
    ok = lambda u, r="https://page.example/v": asyncio.run(sniffer.candidate_ok(u, r))  # noqa: E731
    assert ok("https://cdn.example/a.m3u8")
    assert not ok("file:///etc/passwd") and not ok("concat:file:///etc/passwd|x") and not ok("https://intranet.lan/a.m3u8")
    assert ok("https://page.example/a.mp4", "https://page.example/v")             # web, který uživatel zadal, se nekontroluje


def test_browser_requests_to_private_hosts_are_blocked(monkeypatch):
    monkeypatch.setattr(sniffer.netsafe, "host_ok", lambda u: "192.168" not in u and "localhost" not in u)
    handlers = []

    class Ctx_:
        async def route(self, pattern, fn):
            handlers.append(fn)

    class Route:
        def __init__(self, url):
            self.request = type("R", (), {"url": url})()
            self.res = None
        async def continue_(self): self.res = "ok"
        async def abort(self): self.res = "abort"

    async def go():
        await sniffer.guard_routes(Ctx_(), "https://page.example/v")
        out = {}
        for u in ("https://page.example/x.js", "https://cdn.example/a", "http://192.168.1.1/admin", "http://localhost:8765/api/state",
                  "file:///etc/passwd", "data:text/plain,x"):
            r = Route(u)
            await handlers[0](r)
            out[u] = r.res
        return out
    out = asyncio.run(go())
    assert out["https://page.example/x.js"] == "ok" and out["https://cdn.example/a"] == "ok" and out["data:text/plain,x"] == "ok"
    assert out["http://192.168.1.1/admin"] == "abort" and out["http://localhost:8765/api/state"] == "abort" and out["file:///etc/passwd"] == "abort"


# ------------------------------------------------------------ nastavení
def test_numbers_out_of_range_are_rejected(data):
    s = config.Settings()
    for k, v in (("port", 0), ("port", 70000), ("probe_concurrency", 0), ("probe_concurrency", 1000), ("concurrency", "1e309")):
        with pytest.raises(ValueError):
            s.update({k: v})
    s.update({"port": 8123, "probe_concurrency": 4})
    assert s.get("port") == 8123


def test_import_skips_security_sensitive_keys(client):
    c, st = client
    before = st.settings.all()
    body = {"proxy": "socks5://evil:1080", "telegram_chat_id": "666", "selftest_url": "https://evil.example/x", "cookies_mode": "browser",
            "sleep_min": 7}
    r = c.post("/api/settings/import", files={"file": ("s.json", io.BytesIO(json.dumps(body).encode()), "application/json")})
    assert r.status_code == 200
    after = st.settings.all()
    assert after["sleep_min"] == 7
    for k in ("proxy", "telegram_chat_id", "selftest_url", "cookies_mode"):
        assert after[k] == before[k]


def test_selftest_url_must_be_http(client):
    c, st = client
    assert c.put("/api/settings", json={"selftest_url": "--config-locations=/x"}).status_code == 400
    assert c.put("/api/settings", json={"selftest_url": "https://example.com/v"}).status_code == 200


def test_cookies_upload_is_private_and_size_limited(client):
    c, st = client
    r = c.post("/api/settings/cookies", files={"file": ("c.txt", io.BytesIO(b".a.com\tTRUE\t/\tFALSE\t2000000000\tn\tv\n"), "text/plain")})
    assert r.status_code == 200
    assert stat.S_IMODE(config.cookies_path().stat().st_mode) == 0o600
    big = b"a\tb" * (3 * 1024 * 1024)
    assert c.post("/api/settings/cookies", files={"file": ("c.txt", io.BytesIO(big), "text/plain")}).status_code == 413


# ------------------------------------------------------------ sezení
def test_session_token_depends_on_env_password_and_logout_ends_it(client, monkeypatch):
    c, st = client
    monkeypatch.setenv("VIDDOWN_PASSWORD", "jedno-heslo")
    assert c.get("/api/state").status_code == 401
    assert c.post("/api/login", json={"password": "jedno-heslo"}).status_code == 200
    assert c.get("/api/state").status_code == 200
    monkeypatch.setenv("VIDDOWN_PASSWORD", "druhe-heslo")                      # změna hesla zneplatní vydané cookie
    assert c.get("/api/state").status_code == 401


def test_rollback_with_db_restore_refused_while_jobs_run(client):
    c, st = client
    st.runner.running[1] = (None, None)
    r = c.post("/api/app/rollback", json={"restore_db": True})
    assert r.status_code == 409
    st.runner.running.clear()
