"""Deep review (dávka 3): střední a nízká zjištění a chybějící testy."""
import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace

import httpx
import pytest

from tests.test_catalog import client, e, fake, playlist, rt as _rt, scan  # noqa: F401
from tests.test_catalog_anim import st, with_anims  # noqa: F401
from tests.test_catalog_details import info  # noqa: F401
from tests.test_runner import rt  # noqa: F401
from tests.test_telegram import bot, msg  # noqa: F401
from viddown import catalog, catalogdetails as cd, catalogpreview as cp, nested, pagelist, runner as runner_mod
from viddown.config import Secrets, Settings
from viddown.db import DB
from viddown.resolvers import pages, sniffer


# --- párování animací: společné datum nezjedinečnělo jen proto, že zbylo jedno nevyřízené video ----------
def test_match_listing_counts_resolved_videos_when_judging_uniqueness():
    items = [{"id": 3, "url": "https://x.example/w?viewkey=k333333abc", "thumb_url": "https://img.x/202607/15/333333/t.jpg"}]
    done = [{"id": 1, "url": "https://x.example/w?viewkey=k111111abc", "thumb_url": "https://img.x/202607/15/111111/t.jpg"},
            {"id": 2, "url": "https://x.example/w?viewkey=k222222abc", "thumb_url": "https://img.x/202607/15/222222/t.jpg"}]
    html_ = '<li data-mediabook="https://cdn.x/v/202607/15/111111/p.webm"></li>'               # na stránce jen klip už vyřízeného videa z téhož měsíce
    found, seen, _ = cp.match_listing(html_, "https://x.example/pl", items)                    # bez kontextu vypadá datum 202607 jedinečně
    assert found == {3: "https://cdn.x/v/202607/15/111111/p.webm"}                          # (takhle vznikalo přiřazení cizího klipu)
    found, seen, _ = cp.match_listing(html_, "https://x.example/pl", items, done)
    assert found == {} and seen == set()                                                      # video 3 na stránce není, cizí klip nedostane
    own = html_ + '<li data-mediabook="https://cdn.x/v/202607/15/333333/p.webm"></li>'
    found, seen, _ = cp.match_listing(own, "https://x.example/pl", items, done)
    assert found == {3: "https://cdn.x/v/202607/15/333333/p.webm"} and seen == {3}


# --- miniatury: souběh dvou stahování téže položky ---------------------------------------------------------
def test_thumb_one_skips_when_store_already_saved_a_better_thumbnail(st, fake, info, monkeypatch):
    with_anims(st, fake, {"a": None})
    w = cd.DetailWorker(st)
    row = st.db.query("select * from catalog_items")[0]
    with st.db.conn() as c:
        c.execute("update catalog_items set thumb_file='7.webp', thumb_url='https://img.example/a.jpg' where id=?", (row["id"],))
    calls = []
    monkeypatch.setattr(cd, "download_thumb", lambda *a, **kw: calls.append(1) or "7.jpg")
    asyncio.run(w._thumb_one(dict(row, thumb_url="https://img.example/a.jpg", thumb_alts=None)))
    assert calls == [] and st.db.query("select thumb_file from catalog_items")[0]["thumb_file"] == "7.webp"          # nepřepsalo se


# --- odklad webu a stav položky ------------------------------------------------------------------------------
def test_scan_does_not_erase_a_backoff_set_meanwhile(st, fake, monkeypatch):
    with_anims(st, fake, {"a": None})
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='done'")
    w = cd.DetailWorker(st)

    async def fetch(url, settings=None, timeout=30, **kw):
        w.backoff["example.com"] = {"until": time.monotonic() + 600, "reason": "429", "n": 1}       # jiný worker web mezitím odložil
        return "<html></html>", url
    monkeypatch.setattr(cd.pagelist, "fetch", fetch)
    monkeypatch.setattr(cd.netsafe, "host_ok", lambda u: True)
    asyncio.run(w.process_page_scan(w.pick_page_scan(set())))
    assert "example.com" in w.backoff


def test_details_failure_does_not_hide_an_item_that_was_queued_meanwhile(st, fake, monkeypatch):
    with_anims(st, fake, {"a": None})
    w = cd.DetailWorker(st)
    item = st.db.query("select * from catalog_items")[0]
    with st.db.conn() as c:
        c.execute("update catalog_items set detail_state='pending', state='queued' where id=?", (item["id"],))     # uživatel ho mezitím zařadil ke stažení
    w._finish(dict(item), "failed", "nedostupné", "gone")
    assert st.db.query("select state from catalog_items")[0]["state"] == "queued"


def test_expand_source_keeps_the_list_when_nothing_valid_is_selected(st, fake):
    fake["https://x.example/@k/playlists"] = {"_type": "playlist", "title": "T", "extractor_key": "YoutubeTab",
                                              "entries": [{"_type": "url", "ie_key": "YoutubeTab", "id": "PL1", "url": "https://www.youtube.com/playlist?list=PL1", "title": "A"}]}
    catalog.add_sources(st.db, ["https://x.example/@k/playlists"])
    scan(st, "https://x.example/@k/playlists")
    sid = st.db.query("select id from catalog_sources")[0]["id"]
    res = catalog.expand_source(st.db, sid, ["https://evil.example/x"])
    assert res["added"] == [] and res["skipped"] and st.db.query("select status from catalog_sources")[0]["status"] == "choose"


# --- Chromium ----------------------------------------------------------------------------------------------------
def test_renderer_closes_browser_when_context_setup_fails(monkeypatch, tmp_path):
    closed = []

    class Browser:
        async def new_context(self, **kw):
            raise OSError("cookies.txt zmizel")

        async def close(self):
            closed.append("browser")

    class PW:
        class chromium:
            @staticmethod
            async def launch(**kw):
                return Browser()

        async def stop(self):
            closed.append("pw")

    class Starter:
        async def start(self):
            return PW()
    import playwright.async_api as pa
    monkeypatch.setattr(pa, "async_playwright", lambda: Starter())
    r = sniffer.Renderer(SimpleNamespace(settings={}, cookies_file=None))
    with pytest.raises(OSError):
        asyncio.run(r.__aenter__())
    assert closed == ["browser", "pw"]                                                 # prohlížeč ani ovladač nezůstaly běžet


def test_evaluate_has_a_timeout():
    class Page:
        async def evaluate(self, js):
            await asyncio.sleep(5)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(sniffer._ev(Page(), "() => 1", timeout=0.1))


def test_master_playlist_without_variant_uri_and_encrypted_variants():
    pl = sniffer.parse_m3u8("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\n", "https://h.example/m.m3u8")
    assert pl["master"] and not pl.get("best")                                           # best chybí: volající to musí ustát
    enc = sniffer.parse_m3u8('#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES-CTR,URI="skd://x",KEYFORMAT="com.widevine"\n#EXTINF:4,\na.ts\n', "https://h.example/v.m3u8")
    assert enc["drm"] is True


def test_story_duration_infinity_is_unknown():
    assert pages._finite(float("inf")) is None and pages._finite(None) is None and pages._finite(-1) is None
    assert pages._finite(12.5) == 12.5


# --- pagelist: jen veřejné adresy a celkový čas -------------------------------------------------------------------
def test_pagelist_public_only_rejects_private_targets_and_total_time_is_limited(monkeypatch):
    monkeypatch.setattr(pagelist.netsafe.socket, "getaddrinfo", lambda host, *a, **kw: [(2, 1, 6, "", ("10.0.0.5", 0))])
    with pytest.raises(pagelist.PageError):
        asyncio.run(pagelist.fetch("http://intranet.example.com/x", public_only=True))

    async def slow(*a, **kw):
        await asyncio.sleep(5)
    monkeypatch.setattr(pagelist, "_fetch", slow)
    t0 = time.monotonic()
    with pytest.raises(pagelist.PageError):
        asyncio.run(pagelist.fetch("https://example.com/x", total_timeout=0.1))
    assert time.monotonic() - t0 < 2


# --- nastavení a databáze -----------------------------------------------------------------------------------------------
def test_corrupt_settings_are_kept_as_a_copy_before_defaults_overwrite_them(data):
    path = data / "settings.json"
    path.write_text('{"download_dir": "/nas/x", "telegram_chat_id": "42"', encoding="utf-8")        # chybí závorka
    s = Settings()
    assert s.get("telegram_chat_id") != "42"                                                          # použily se výchozí hodnoty
    s.update({"language": "en"})
    kept = data / "settings.json.corrupt"
    assert kept.exists() and '"/nas/x"' in kept.read_text(encoding="utf-8")                          # původní soubor se dá obnovit


def test_corrupt_secrets_are_kept_as_a_copy(data):
    (data / "secrets.json").write_text("{špatně", encoding="utf-8")
    assert Secrets().has_password() is False
    assert (data / "secrets.json.corrupt").exists()


def test_migrating_an_up_to_date_database_is_a_noop(data):
    db = DB(data / "m.db")
    assert db.migrate() == []                                                                          # druhý proces najde hotovo a nic neprovádí


def test_target_available_does_not_create_a_missing_mount_path(tmp_path):
    ok, msg = runner_mod.target_available(str(tmp_path / "nas" / "sdileni" / "Video"))
    assert ok is False and not (tmp_path / "nas").exists()                                            # odpojený NAS: cesta se nezakládá
    (tmp_path / "ok").mkdir()
    assert runner_mod.target_available(str(tmp_path / "ok" / "nova"))[0] is True                       # nová poslední složka se založí


# --- Telegram: aktualizace jen z osobního chatu ----------------------------------------------------------------------------
def test_app_update_buttons_work_only_in_private_chat(bot):
    called = []

    async def app_action(jid):
        called.append(jid)
    bot._app_action = app_action

    def cb(chat_type):
        return {"update_id": 3, "callback_query": {"id": "q", "data": "app:update", "message": {"message_id": 6, "chat": {"id": 42, "type": chat_type}, "text": "x"}}}
    asyncio.run(bot.handle(cb("supergroup")))
    assert called == []                                                                               # ve skupině nic
    asyncio.run(bot.handle(cb("private")))
    assert called == ["update"]


def test_finalize_does_not_create_the_root_of_a_disconnected_target(rt):
    jid = rt.db.add("https://x/v", status="queued", kind="video")
    staging = rt.staging(jid)
    staging.mkdir(parents=True, exist_ok=True)
    f = staging / "V.mp4"
    f.write_bytes(b"x")
    rt.settings.update({"download_dir": str(staging.parent.parent / "nas" / "sdileni" / "Video")})   # rodič (NAS) chybí
    from viddown.resolvers import ResolveError
    with pytest.raises(ResolveError) as e:
        rt._finalize(jid, {"file": f, "thumb": None, "log": ""}, "ytdlp", staging)
    assert e.value.kind == "target" and f.exists()
    assert not (staging.parent.parent / "nas").exists()                                                # cesta odpojeného NAS se nezaložila


def test_api_passes_duration_and_age_filters_through(client):
    c, s = client
    now = time.time()
    with s.db.conn() as conn:
        conn.execute("insert into catalog_sources(url, kind, title, status, added_at) values('https://x.example/a', 'channel', 'Z', 'done', 1)")
        for i, (title, dur, pub) in enumerate([("kratke", 15, now - 86400), ("minuta", 45, now - 40 * 86400), ("dlouhe", 7200, now - 400 * 86400), ("bez", None, 0)]):
            conn.execute("insert into catalog_items(source_id, key, url, host, title, pos, state, detail_state, added_at, updated_at, duration, published_at) "
                         "values(1, ?, ?, 'x.example', ?, ?, 'new', 'done', 1, 1, ?, ?)", (f"k{i}", f"https://x.example/{i}", title, i, dur, pub))
    titles = lambda q: sorted(i["title"] for i in c.get("/api/catalog/items?" + q).json()["items"])  # noqa: E731
    assert titles("") == ["bez", "dlouhe", "kratke", "minuta"]
    assert titles("dur=20") == ["kratke"] and titles("dur=60") == ["minuta"] and titles("dur=over") == ["dlouhe"] and titles("dur=unknown") == ["bez"]
    assert titles("dur=20,over") == ["dlouhe", "kratke"]
    assert titles("age=week") == ["kratke"] and titles("age=year") == ["kratke", "minuta"]
    assert titles("age=week&dur=60") == []                                                            # filtry se kombinují
    got = c.get("/api/catalog/items?sort=published&dir=asc").json()["items"]
    assert [i["title"] for i in got][:2] == ["dlouhe", "minuta"] and got[-1]["title"] == "bez"        # nejstarší první, neznámé na konec


# --- proxy ---------------------------------------------------------------------------------------------------------------
def test_proxy_kw_accepts_http_and_socks_and_never_falls_back_to_direct(monkeypatch):
    from viddown import netsafe
    assert netsafe.proxy_kw("") == {} and netsafe.proxy_kw(None) == {}
    assert netsafe.proxy_kw("http://p.example:8080") == {"proxy": "http://p.example:8080"}
    assert netsafe.proxy_kw("p.example:8080") == {"proxy": "http://p.example:8080"}          # bez schématu = HTTP proxy
    import importlib.util as iu
    real = iu.find_spec
    monkeypatch.setattr(iu, "find_spec", lambda name, *a, **kw: object() if name == "socksio" else real(name, *a, **kw))
    assert netsafe.proxy_kw("socks5://127.0.0.1:1080") == {"proxy": "socks5://127.0.0.1:1080"}
    assert netsafe.proxy_kw("socks5h://127.0.0.1:1080")["proxy"].startswith("socks5h")
    monkeypatch.setattr(iu, "find_spec", lambda name, *a, **kw: None if name == "socksio" else real(name, *a, **kw))
    with pytest.raises(netsafe.ProxyError):
        netsafe.proxy_kw("socks5://127.0.0.1:1080")                                          # bez podpory SOCKS raději chyba než přímé spojení
    with pytest.raises(netsafe.ProxyError):
        netsafe.proxy_kw("ftp://p.example")


def test_fetchers_fail_closed_when_the_proxy_is_unusable(tmp_path):
    from viddown import netsafe
    with pytest.raises(netsafe.ProxyError):
        netsafe.fetch_limited("https://example.com/x", {}, 1000, "ftp://p.example")
    with pytest.raises(pagelist.PageError):
        asyncio.run(pagelist.fetch("https://example.com/x", {"proxy": "ftp://p.example"}))
    assert cd.download_anim(tmp_path, 1, "https://example.com/x.mp4", 1000, None, "ftp://p.example") is None     # nic se neodešle přímo


# --- Telegram: skupina ---------------------------------------------------------------------------------------------------
def group_msg(text, uid, chat=42):
    return {"update_id": 5, "message": {"message_id": 9, "from": {"id": uid}, "chat": {"id": chat, "type": "supergroup"}, "text": text}}


def test_group_chat_needs_an_allowed_user(bot):
    bot.settings.update({"telegram_user_ids": ""})
    n = len(bot.sent)
    asyncio.run(bot.handle(group_msg("/fronta", 111)))
    assert len(bot.sent) == n                                                         # bez povolených uživatelů se skupina ignoruje
    bot.settings.update({"telegram_user_ids": "111, 222"})
    asyncio.run(bot.handle(group_msg("/fronta", 333)))
    assert len(bot.sent) == n                                                         # cizí člen skupiny nic nezmůže
    asyncio.run(bot.handle(group_msg("/fronta", 222)))
    assert len(bot.sent) == n + 1 and "prázdná" in bot.sent[-1][1]["text"]            # povolený uživatel ano
    asyncio.run(bot.handle(msg("/fronta")))                                           # osobní chat funguje beze změny
    assert len(bot.sent) == n + 2
