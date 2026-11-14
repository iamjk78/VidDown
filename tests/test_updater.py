"""Aktualizace zevnitř, etapa 3: stav a banner, kontrola podle rozvrhu, oznámení, automatický režim, API, Telegram."""
import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_appupdate_remote import REPO, TOKEN, Fake, break_module  # noqa: F401
from tests.test_subscriptions import State, rt  # noqa: F401
from viddown import appupdate as au
from viddown import updater
from viddown.config import Secrets, Settings
from viddown.db import DB
from viddown.server import create_app


class Bot:
    def __init__(self):
        self.state, self.sent = "ok", []

    def notify_threadsafe(self, key, **kw):
        self.sent.append((key, kw))

    def keys(self):
        return [k for k, _ in self.sent]


class St:
    def __init__(self, data):
        self.data = data
        self.settings = Settings()
        self.secrets = Secrets()
        self.db = DB(data / "viddown.db")
        self.runner = SimpleNamespace(running={})
        self.bot = Bot()
        self.stop = asyncio.Event()
        self.restart = False


@pytest.fixture
def gh(monkeypatch):
    f = Fake()
    monkeypatch.setenv("VIDDOWN_GITHUB_API", f.url)
    for k in ("VIDDOWN_APP_ACTIVE", "VIDDOWN_BASE_VERSION", "VIDDOWN_IMAGE_API", "VIDDOWN_BASE_SCHEMA", "VIDDOWN_APP_UPDATE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(au.AppStore, "selftest", lambda self, ver, skip_engines=False, timeout=240: (True, {"ok": True, "checks": []}))
    updater._APPLYING["on"] = False
    updater._BANNER_CACHE["t"] = 0.0
    yield f
    f.close()


@pytest.fixture
def st(data, gh):
    s = St(data)
    s.settings.update({"app_update_repo": REPO})
    s.secrets.set_app_update_token(TOKEN)
    return s


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------ stav a banner
def test_status_and_banner_kinds(st, gh, tmp_path):
    s = updater.status(st)
    assert s["banner"] is None and s["mode"] == "notify" and s["hours"] == 24 and s["token_set"] and not s["prepared"]
    assert TOKEN not in str(s)                                           # token se nikdy nevrací
    gh.publish(tmp_path)
    updater.do_check(st)
    assert updater.status(st)["banner"] == {"kind": "available", "version": "9.9.9"}
    updater.do_update(st)
    b = updater.status(st)
    assert b["prepared"] and b["banner"] == {"kind": "prepared", "version": "9.9.9"}
    updater._APPLYING["on"] = True
    assert updater.status(st)["banner"]["kind"] == "applying"
    updater._APPLYING["on"] = False


def test_rolled_back_banner_can_be_dismissed(st, tmp_path):
    ast = updater.store(st)
    ast.skip("9.9.9", "zkouška")
    s = ast.state()
    s["events"].append({"t": time.time(), "kind": "rolled_back", "version": "9.9.9", "msg": "nenaběhla; zpět na 0.1.0"})
    ast.save(s)
    b = updater.status(st)["banner"]
    assert b["kind"] == "rolled_back" and b["version"] == "9.9.9" and "zpět" in b["msg"]
    ast.update_state(dismissed=b["t"])
    assert updater.status(st)["banner"] is None
    s = ast.state()
    s["events"].append({"t": time.time() - 15 * 86400, "kind": "rolled_back", "version": "9.9.8", "msg": "stará"})
    ast.save(s)
    ast.update_state(dismissed=0)
    assert updater.status(st)["banner"]["version"] == "9.9.9"           # starší než 14 dní se nezobrazí


def test_busy_guard_blocks_parallel_updates(st, gh, tmp_path):
    gh.publish(tmp_path)
    assert updater._BUSY.acquire(blocking=False)
    try:
        with pytest.raises(au.UpdateError, match="už probíhá"):
            updater.do_check(st)
    finally:
        updater._BUSY.release()


# ------------------------------------------------------------ rozvrh a oznámení
def test_tick_notify_mode_announces_once_and_respects_interval(st, gh, tmp_path):
    gh.publish(tmp_path)
    run(updater.tick(st))                                               # první kontrola + první průchod oznámení
    run(updater.tick(st))
    run(updater.tick(st))
    assert st.bot.keys() == ["app_update_available"] and st.bot.sent[0][1]["version"] == "9.9.9"
    assert updater.status(st)["prepared"] is False                      # režim „oznámit“ nic neinstaluje
    n = len(gh.calls)
    run(updater.tick(st))
    assert len(gh.calls) == n                                           # interval ještě neuplynul
    chk = updater.store(st).state()["check"]
    chk["at"] -= 25 * 3600
    updater.store(st).update_state(check=chk)
    run(updater.tick(st))
    assert len(gh.calls) > n and st.bot.keys() == ["app_update_available"]   # nová kontrola, ale stejná verze se neoznamuje znovu


def test_tick_off_mode_does_nothing(st, gh, tmp_path):
    st.settings.update({"app_update_mode": "off"})
    gh.publish(tmp_path)
    run(updater.tick(st))
    assert gh.calls == [] and st.bot.sent == []


def test_failed_check_is_retried_after_an_hour(st, gh, tmp_path):
    gh.publish(tmp_path)
    st.secrets.set_app_update_token("spatny")
    run(updater.tick(st))
    chk = updater.store(st).state()["check"]
    assert chk["status"] == "error" and not updater.check_due(st)
    chk["at"] -= 3601
    updater.store(st).update_state(check=chk)
    assert updater.check_due(st)


def test_events_are_announced_once_and_old_ones_not_at_all(st):
    ast = updater.store(st)
    s = ast.state()
    s["events"] = [{"t": 100.0, "kind": "healthy", "version": "9.9.0", "msg": ""}]
    ast.save(s)
    updater.announce_pending(st)                                         # první běh: stará událost se jen zapamatuje
    assert st.bot.sent == []
    s = ast.state()
    s["events"] += [{"t": time.time(), "kind": "healthy", "version": "9.9.9", "msg": ""},
                    {"t": time.time() + 1, "kind": "rolled_back", "version": "9.9.10", "msg": "padla"},
                    {"t": time.time() + 2, "kind": "switched", "version": "9.9.11", "msg": "x"}]
    ast.save(s)
    updater.announce_pending(st)
    updater.announce_pending(st)
    assert st.bot.keys() == ["app_update_done", "app_update_rolled_back"]
    assert st.bot.sent[1][1]["reason"] == "padla"


def test_nothing_is_announced_while_bot_is_offline(st):
    ast = updater.store(st)
    ast.update_state(announced=0, events=[{"t": 5.0, "kind": "healthy", "version": "9.9.9", "msg": ""}])
    st.bot.state = "off"
    updater.announce_pending(st)
    assert st.bot.sent == [] and ast.state()["announced"] == 0           # po připojení bota se pošle
    st.bot.state = "ok"
    updater.announce_pending(st)
    assert st.bot.keys() == ["app_update_done"]


# ------------------------------------------------------------ automatický režim a restart po doběhnutí
def test_auto_mode_updates_pauses_queue_softly_and_restarts_when_idle(st, gh, tmp_path):
    st.settings.update({"app_update_mode": "auto"})
    gh.publish(tmp_path)
    run(updater.tick(st))
    assert st.restart is True and updater.store(st).state()["current"] == "9.9.9"
    assert st.db.kv_get("queue_paused") is True and st.db.kv_get("queue_pause_reason") == "user"
    assert st.db.kv_get("queue_pause_hard") is False and st.db.kv_get("update_resume") is True
    assert "app_update_auto" in st.bot.keys()
    # po restartu aplikace se fronta, kterou jsme pozastavili my, obnoví
    updater.startup(st)
    assert st.db.kv_get("queue_paused") is False and st.db.kv_get("update_resume") is False


def test_apply_waits_for_running_downloads_then_restarts(st, gh, tmp_path, monkeypatch):
    gh.publish(tmp_path)
    updater.do_update(st)
    monkeypatch.setattr(updater, "POLL", 0.01)
    st.runner.running = {1: object()}

    async def go():
        t = asyncio.create_task(updater.apply_when_idle(st))
        await asyncio.sleep(0.1)
        assert not t.done() and st.restart is False
        assert st.db.kv_get("queue_paused") is True and st.db.kv_get("queue_pause_hard") is False   # rozpracované doběhnou
        assert updater.status(st)["banner"]["kind"] == "applying"
        st.runner.running = {}
        return await t
    assert run(go()) == "restarting" and st.restart is True


def test_user_resuming_the_queue_cancels_the_restart(st, gh, tmp_path, monkeypatch):
    gh.publish(tmp_path)
    updater.do_update(st)
    monkeypatch.setattr(updater, "POLL", 0.01)
    st.runner.running = {1: object()}

    async def go():
        t = asyncio.create_task(updater.apply_when_idle(st))
        await asyncio.sleep(0.05)
        st.db.kv_set("queue_paused", False)                              # uživatel frontu obnovil
        return await t
    assert run(go()) == "cancelled"
    assert st.restart is False and st.db.kv_get("update_resume") is False and updater._APPLYING["on"] is False


def test_long_wait_is_postponed_and_queue_resumed(st, gh, tmp_path, monkeypatch):
    gh.publish(tmp_path)
    updater.do_update(st)
    monkeypatch.setattr(updater, "POLL", 0.01)
    monkeypatch.setattr(updater, "WAIT_MAX", 0.05)
    st.runner.running = {1: object()}
    assert run(updater.apply_when_idle(st)) == "postponed"
    assert st.db.kv_get("queue_paused") is False and st.restart is False and "app_update_postponed" in st.bot.keys()
    assert updater._APPLYING["on"] is False


def test_existing_user_pause_is_left_alone(st, gh, tmp_path):
    gh.publish(tmp_path)
    updater.do_update(st)
    st.db.kv_set("queue_paused", True)
    st.db.kv_set("queue_pause_reason", "user")
    assert run(updater.apply_when_idle(st)) == "restarting"
    assert st.db.kv_get("update_resume") is False
    updater.startup(st)
    assert st.db.kv_get("queue_paused") is True                          # uživatelovu pauzu nerušíme


def test_apply_requires_prepared_version(st):
    with pytest.raises(au.UpdateError, match="připravená"):
        run(updater.apply_when_idle(st))


def test_auto_update_failure_is_reported_and_version_skipped(st, gh, tmp_path, monkeypatch):
    monkeypatch.setattr(au.AppStore, "selftest", lambda self, ver, skip_engines=False, timeout=240: (False, {"ok": False, "checks": [{"name": "moduly", "ok": False, "detail": "boom"}]}))
    st.settings.update({"app_update_mode": "auto"})
    gh.publish(tmp_path)
    run(updater.tick(st))
    assert "app_update_failed" in st.bot.keys() and st.restart is False
    assert "9.9.9" in updater.store(st).state()["skipped"] and st.db.kv_get("queue_paused") in (None, False)


# ------------------------------------------------------------ API
def make_client(rt, data, monkeypatch, gh):
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    s = State(rt, data)
    s.stop, s.restart, s.bot = asyncio.Event(), False, None
    s.engines_cache = lambda: []
    s.settings.update({"app_update_repo": REPO})
    s.secrets.set_app_update_token(TOKEN)
    return TestClient(create_app(s)), s


def test_api_flow_check_update_apply_rollback(rt, data, monkeypatch, gh, tmp_path):
    c, s = make_client(rt, data, monkeypatch, gh)
    gh.publish(tmp_path)
    j = c.get("/api/app").json()
    assert j["banner"] is None and j["token_set"] is True and "token" not in j
    j = c.post("/api/app/check").json()
    assert j["check"]["status"] == "available" and j["banner"]["kind"] == "available"
    assert c.post("/api/app/apply").status_code == 409                    # nic připraveného
    up = c.post("/api/app/update", json={}).json()
    assert up["result"]["version"] == "9.9.9" and up["status"]["prepared"] is True
    assert c.get("/api/state").json()["app"]["kind"] in ("prepared", "applying")
    ap = c.post("/api/app/apply")
    assert ap.status_code == 200
    time.sleep(0.3)
    assert s.restart is True
    updater._APPLYING["on"] = False
    rb = c.post("/api/app/rollback", json={})
    assert rb.status_code == 200 and rb.json()["current"] is None and "9.9.9" in rb.json()["skipped"]
    un = c.post("/api/app/unskip", json={"version": "9.9.9"}).json()
    assert "9.9.9" not in un["skipped"]


def test_api_errors_and_token_and_dismiss(rt, data, monkeypatch, gh, tmp_path):
    c, s = make_client(rt, data, monkeypatch, gh)
    r = c.post("/api/app/rollback", json={})
    assert r.status_code == 400 and "aktualizovaná verze" in r.json()["detail"]
    s.secrets.set_app_update_token("")
    r = c.post("/api/app/check")
    assert r.status_code == 400 and "token" in r.json()["detail"]
    r = c.post("/api/app/token", json={"token": "novy-token"})
    assert r.status_code == 200 and r.json()["token_set"] is True and "novy-token" not in r.text
    assert s.secrets.app_update_token == "novy-token"
    assert c.post("/api/app/token", json={"token": ""}).json()["token_set"] is False
    assert c.post("/api/app/dismiss", json={"t": 123}).json()["dismissed"] == 123
    assert c.put("/api/settings", json={"app_update_mode": "auto", "app_update_hours": 12}).status_code == 200
    assert c.put("/api/settings", json={"app_update_mode": "kdyz"}).status_code == 400
    assert c.put("/api/settings", json={"app_update_hours": 5}).status_code == 400
    assert c.put("/api/settings", json={"app_update_repo": "../x"}).status_code == 400


# ------------------------------------------------------------ Telegram
def test_telegram_app_command_buttons_and_actions(st, gh, tmp_path, monkeypatch):
    from tests.test_telegram import FakeEngines, msg
    from viddown.runner import Runner
    from viddown.telegram import TelegramBot
    st.settings.update({"telegram_chat_id": "42", "download_dir": str(tmp_path)})
    r = Runner(st.db, st.settings, FakeEngines(), st.data)
    b = TelegramBot(r, st.db, st.settings, st.secrets, FakeEngines())
    b.state, b.sent, b.app = "ok", [], st

    async def call(method, http_timeout=30, **p):
        b.sent.append((method, p))
        return {"message_id": 100 + len(b.sent)}
    b.call = call
    gh.publish(tmp_path)

    def texts():
        return [p.get("text", "") for m, p in b.sent if m == "sendMessage"]

    asyncio.run(b.handle(msg("/aplikace")))
    last = [p for m, p in b.sent if m == "sendMessage"][-1]
    assert "9.9.9" in last["text"] and last["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "app:update"
    cb = lambda d: {"update_id": 2, "callback_query": {"id": "q", "data": d, "message": {"message_id": 5, "chat": {"id": 42, "type": "private"}, "text": "x"}}}
    asyncio.run(b.handle(cb("app:update")))
    assert updater.status(st)["prepared"] is True
    last = [p for m, p in b.sent if m == "sendMessage"][-1]
    cbs = [x["callback_data"] for row in last["reply_markup"]["inline_keyboard"] for x in row]
    assert cbs == ["app:apply", "app:restart"]

    async def restart():
        await b.handle(cb("app:restart"))
        assert st.restart is True
    asyncio.run(restart())
    assert any("Restartuji" in x for x in texts())
