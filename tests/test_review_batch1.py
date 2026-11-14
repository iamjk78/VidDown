"""Deep review (dávka 1): bezpečnost serveru, SSRF, odolnost smyček a malé chyby."""
import asyncio

import httpx
import pytest

from tests.test_api import client  # noqa: F401
from tests.test_catalog import fake  # noqa: F401
from tests.test_catalog_anim import st, with_anims  # noqa: F401
from tests.test_catalog_details import info  # noqa: F401
from tests.test_engines import install, mgr  # noqa: F401
from viddown import catalogdetails as cd, netsafe, thumbs
from viddown.config import Secrets


# --- mazání verze enginu ---------------------------------------------------------------------------
def test_engine_remove_refuses_paths_outside_installed_versions(mgr, tmp_path):
    install(mgr, "1.0")
    install(mgr, "2.0")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "x").write_text("data")
    e = mgr.get("fake")
    for bad in (str(victim), "../../" + victim.name, "", "9.9", None, 5, "1.0/.."):
        with pytest.raises(ValueError):
            e.remove(bad)
    assert (victim / "x").exists() and e.current() == "2.0"
    assert [v["version"] for v in e.versions()] == ["2.0", "1.0"]
    e.remove("1.0")                                                       # skutečná starší verze jde smazat
    assert [v["version"] for v in e.versions()] == ["2.0"]


def test_engine_remove_endpoint_rejects_bad_bodies(client):
    c, st = client
    for body in ({}, {"version": 5}, [], {"version": "/nas"}):
        r = c.post("/api/engines/yt-dlp/remove", json=body)
        assert r.status_code in (400, 404), (body, r.status_code)


# --- Host a Origin ---------------------------------------------------------------------------------
def test_dns_rebinding_host_is_rejected_but_lan_names_pass(client):
    c, st = client
    assert c.get("/api/session", headers={"host": "evil.example.com"}).status_code == 400
    assert c.get("/api/session", headers={"host": "evil.example.com:8765"}).status_code == 400
    for ok in ("127.0.0.1:8765", "localhost:8765", "192.168.1.5", "[::1]:8765", "nas", "nas.local:8765", "mac.tailnet.ts.net", "host.docker.internal:8765"):
        assert c.get("/api/session", headers={"host": ok}).status_code == 200, ok


def test_extra_hosts_from_environment(client, monkeypatch):
    monkeypatch.setenv("VIDDOWN_ALLOWED_HOSTS", "nas.example.com, other.example.org")
    from fastapi.testclient import TestClient
    from viddown.server import create_app
    c2 = TestClient(create_app(client[1]))
    assert c2.get("/api/session", headers={"host": "nas.example.com"}).status_code == 200
    assert c2.get("/api/session", headers={"host": "evil.example.com"}).status_code == 400


def test_cross_origin_writes_are_rejected(client):
    c, st = client
    h = {"host": "127.0.0.1:8765"}
    assert c.post("/api/queue/pause", headers={**h, "origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/queue/pause", headers={**h, "origin": "null"}).status_code == 403
    assert c.post("/api/queue/pause", headers={**h, "sec-fetch-site": "cross-site"}).status_code == 403
    assert c.post("/api/queue/pause", headers={**h, "origin": "http://127.0.0.1:8765"}).status_code == 200      # stejný původ
    assert c.post("/api/queue/resume", headers=h).status_code == 200                                             # bez Origin (curl, skripty)
    assert c.get("/api/session", headers={**h, "origin": "https://evil.example"}).status_code == 200            # čtení blokuje prohlížeč (CORS)


# --- sezení a heslo --------------------------------------------------------------------------------
def test_password_change_and_logout_invalidate_old_cookies(client):
    c, st = client
    r = c.post("/api/settings/password", json={"password": "prvni-heslo"})
    assert r.status_code == 200
    old = c.cookies.get("vd_session")
    assert old and c.get("/api/state").status_code == 200
    c.post("/api/settings/password", json={"password": "druhe-heslo"})
    new = c.cookies.get("vd_session")
    assert new != old
    c.cookies.clear()
    c.cookies.set("vd_session", old)
    assert c.get("/api/state").status_code == 401                          # starý token po změně hesla neplatí
    c.cookies.clear()
    assert c.post("/api/login", json={"password": "druhe-heslo"}).status_code == 200
    tok = c.cookies.get("vd_session")
    assert c.get("/api/state").status_code == 200
    c.post("/api/logout")
    c.cookies.clear()
    c.cookies.set("vd_session", tok)
    assert c.get("/api/state").status_code == 401                          # po odhlášení neplatí ani zkopírovaná cookie


def test_password_with_diacritics_from_environment(monkeypatch, data):
    monkeypatch.setenv("VIDDOWN_PASSWORD", "žluťoučký")
    s = Secrets()
    assert s.check_password("žluťoučký") is True and s.check_password("špatné") is False and s.check_password("zlutoucky") is False


# --- SSRF ------------------------------------------------------------------------------------------
def test_idna_and_exotic_hosts_are_checked_by_the_name_httpx_connects_to(monkeypatch):
    monkeypatch.setattr(netsafe.socket, "getaddrinfo", lambda host, *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))] if host == "evilss.com" else [(2, 1, 6, "", ("192.168.1.9", 0))])
    assert netsafe.host_ok("http://evilß.com/x.mp4") is False               # httpx se připojí na xn--evil-yna.com, ne na evilss.com
    assert netsafe.host_ok("http://example.com/x") is False                  # přeložené na soukromou adresu
    assert netsafe.literal_ok("http://[64:ff9b::7f00:1]/x") is False         # NAT64 s vloženou 127.0.0.1
    assert netsafe.literal_ok("http://[::ffff:127.0.0.1]/x") is False
    assert netsafe.literal_ok("http://[2002:c0a8:0101::1]/x") is False       # 6to4 s 192.168.1.1
    assert netsafe.literal_ok("http://8.8.8.8/x") is True
    assert netsafe.literal_ok("http://ｅｘａｍｐｌｅ.com/x") in (True, False)     # plnošířková písmena: ať už se přijmou, nebo odmítnou, nikdy výjimka
    assert netsafe.literal_ok("http://a" + "b" * 70 + ".com/x") in (True, False)  # příliš dlouhé části nesmí vyhodit výjimku


def test_invalid_urls_do_not_raise_from_fetchers(tmp_path, monkeypatch):
    monkeypatch.setattr(netsafe.socket, "getaddrinfo", lambda *a, **kw: (_ for _ in ()).throw(OSError("bez DNS")))
    assert netsafe.fetch_limited("http://exa mple.com/x", {}, 1000) is None
    assert netsafe.fetch_limited("http://" + "a" * 300 + ".com/x", {}, 1000) is None
    assert cd.download_anim(tmp_path, 1, "http://ｅｘａｍｐｌｅ.com/\x00x.mp4", 1000) is None
    assert thumbs.fetch("http://exa mple.com/x.jpg", tmp_path / "t.jpg") is False


def test_thumbnail_fetch_refuses_private_targets_and_redirects(tmp_path, monkeypatch):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.host == "cdn.example":
            return httpx.Response(302, headers={"location": "http://192.168.1.1/admin.jpg"})
        return httpx.Response(200, content=b"\xff\xd8\xff" + b"x" * 50)
    real = httpx.Client
    monkeypatch.setattr(netsafe.httpx, "Client", lambda *a, **kw: real(*a, transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(netsafe, "host_ok", lambda url: netsafe.literal_ok(url))
    assert thumbs.fetch("http://192.168.1.1/x.jpg", tmp_path / "a.jpg") is False          # přímo soukromá adresa
    assert thumbs.fetch("https://cdn.example/x.jpg", tmp_path / "b.jpg") is False         # přesměrování do domácí sítě
    assert seen == ["https://cdn.example/x.jpg"]                                         # na soukromou adresu se vůbec nesáhlo
    monkeypatch.setattr(thumbs, "MAX_THUMB_BYTES", 10)
    assert thumbs.fetch("https://ok.example/x.jpg", tmp_path / "c.jpg") is False          # nad limit velikosti


def test_one_bad_animation_or_thumbnail_is_marked_failed_instead_of_stopping_the_loop(st, fake, info, monkeypatch):
    with_anims(st, fake, {"a": "http://ｅｘａｍｐｌｅ.com/a.mp4", "b": "https://c/b.gif"})
    w = cd.DetailWorker(st)

    def boom(*a, **kw):
        raise httpx.InvalidURL("vadná adresa")
    monkeypatch.setattr(cd, "download_anim", boom)
    monkeypatch.setattr(cd, "download_thumb", boom)
    rows = st.db.query("select id, url, anim_url, thumb_url, thumb_alts from catalog_items order by id")
    for r in rows:
        asyncio.run(w._anim_one(r))
        asyncio.run(w._thumb_one(r))
    got = st.db.query("select anim_file, thumb_file from catalog_items")
    assert all(g["anim_file"] == "" and g["thumb_file"] == "" for g in got)      # označeno jako nepodařené, takže se nezkouší pořád dokola
    assert not w.pending_anims(5)
