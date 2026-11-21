"""Keep2Share ve frontě: odpočet, captcha od uživatele, neexistující soubor, stahování – s falešným API (bez sítě)."""
import asyncio

import httpx
import pytest

from viddown import runner as runner_mod
from viddown.config import Settings
from viddown.db import DB
from viddown.resolvers import ProcHolder, ResolveError, k2s
from tests.test_runner import FakeEngines

URL = "https://k2s.cc/file/abc123/film.rar"


def test_parse_captcha_reply():
    assert k2s.parse_captcha_reply("#12 abc") == (12, "abc")
    assert k2s.parse_captcha_reply("  12   xy9 ") == (12, "xy9")
    assert k2s.parse_captcha_reply("ahoj") is None
    assert k2s.parse_captcha_reply("#x abc") is None
    assert k2s.parse_captcha_reply("/start 1") is None


def test_fetch_file_streams_to_disk_and_reports_progress(tmp_path):
    payload = b"x" * 200_000

    def handler(req):
        return httpx.Response(200, content=payload, headers={"content-length": str(len(payload))})

    seen = []
    dest = tmp_path / "f.rar"
    size = asyncio.run(k2s.fetch_file("https://dl.example.test/f", dest, lambda **kw: seen.append(kw),
                                      lambda: None, transport=httpx.MockTransport(handler)))
    assert size == len(payload) and dest.read_bytes() == payload
    assert not seen or seen[-1].get("total") in (None, len(payload))


def test_fetch_file_http_error_is_network_kind(tmp_path):
    t = httpx.MockTransport(lambda req: httpx.Response(503))
    with pytest.raises(k2s.K2SError) as e:
        asyncio.run(k2s.fetch_file("https://dl.example.test/f", tmp_path / "f", lambda **kw: None, lambda: None, transport=t))
    assert e.value.kind == "network"


class ScriptedClient:
    """Falešný klient API: vrací odpovědi podle `script` (výjimky se vyhodí, hodnoty se vrátí)."""
    script: list = []
    calls: list = []
    challenge = k2s.Challenge("c1", "https://captcha.example.test")

    def __init__(self, *a, **k):
        pass

    def get_url(self, fid, token, key, ch, answer):
        ScriptedClient.calls.append({"fid": fid, "token": token, "challenge": ch and ch.challenge, "answer": answer})
        item = ScriptedClient.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def request_captcha(self):
        return ScriptedClient.challenge

    def captcha_image(self, ch):
        return b"\x89PNG-test"

    def close(self):
        pass


@pytest.fixture()
def rt(data, monkeypatch, tmp_path):
    s = Settings()
    s.update({"download_dir": str(tmp_path / "dl"), "sleep_min": 0, "sleep_max": 0, "concurrency": 1,
              "engine_auto_update": False, "min_free_gb": 0})
    db = DB(data / "t.db")
    r = runner_mod.Runner(db, s, FakeEngines(), data)
    monkeypatch.setattr(runner_mod.k2s, "Client", ScriptedClient)
    monkeypatch.setattr(r, "_k2s_retry_s", lambda s: 0.01)
    ScriptedClient.script, ScriptedClient.calls = [], []
    return r, db


def fake_fetch(content: bytes):
    async def fetch(url, dest, on_progress, check, transport=None):
        dest.write_bytes(content)
        return len(content)
    return fetch


def run_job(r, db, monkeypatch, content=b"video-bytes"):
    monkeypatch.setattr(runner_mod.k2s, "fetch_file", fake_fetch(content))
    jid = db.add(URL, status="running")
    job = db.get(jid)
    staging = r.staging(jid)
    res = asyncio.run(r._dl_k2s(job, {}, r.ctx(), staging, ProcHolder(), lambda **kw: None))
    return jid, res


def test_wait_then_download(rt, monkeypatch):
    r, db = rt
    ScriptedClient.script = [k2s.K2SError("wait", 41, "wait"), "https://dl.example.test/f.rar"]
    jid, res = run_job(r, db, monkeypatch)
    assert res["file"].read_bytes() == b"video-bytes" and res["file"].suffix == ".rar"
    assert len(ScriptedClient.calls) == 2 and ScriptedClient.calls[0]["fid"] == "abc123"


def test_captcha_is_answered_by_user_then_download(rt, monkeypatch):
    r, db = rt
    ScriptedClient.script = [k2s.K2SError("captcha", 30, "captcha"), "https://dl.example.test/f.rar"]
    sent = []

    async def sender(jid, img):
        sent.append((jid, img))
        assert r.answer_captcha(jid, "xyz")           # uživatel odpoví v chatu

    r.captcha_sender = sender
    jid, res = run_job(r, db, monkeypatch)
    assert sent and sent[0][1] == b"\x89PNG-test"
    last = ScriptedClient.calls[-1]
    assert last["challenge"] == "c1" and last["answer"] == "xyz"


def test_captcha_without_telegram_waits_instead_of_guessing(rt, monkeypatch):
    r, db = rt
    r.captcha_sender = None
    ScriptedClient.script = [k2s.K2SError("captcha", 30, "captcha"), "https://dl.example.test/f.rar"]
    jid, res = run_job(r, db, monkeypatch)
    assert res["file"].exists()
    assert all(c["answer"] is None for c in ScriptedClient.calls)     # bez Telegramu se nic nevyluštilo


def test_missing_file_fails_with_gone_kind(rt, monkeypatch):
    r, db = rt
    ScriptedClient.script = [k2s.K2SError("neexistuje", 20, "gone")]
    with pytest.raises(ResolveError) as e:
        run_job(r, db, monkeypatch)
    assert e.value.kind == "gone"


def test_answer_for_job_not_waiting_is_refused(rt):
    r, db = rt
    assert r.answer_captcha(999, "abc") is False


def test_k2s_is_detected_by_url_only():
    assert runner_mod.Runner.is_k2s(URL)
    assert not runner_mod.Runner.is_k2s("https://www.youtube.com/watch?v=x")


def test_login_is_used_and_token_cached(rt, monkeypatch, tmp_path):
    from viddown.config import Secrets
    r, db = rt
    sec = Secrets(tmp_path / "secrets.json")
    sec.set_k2s_login("uzivatel", "heslo")
    r.secrets = sec
    logins = []
    monkeypatch.setattr(ScriptedClient, "login", lambda self, u, p: (logins.append((u, p)), "tok1")[1], raising=False)
    ScriptedClient.script = ["https://dl.example.test/f.rar"]
    run_job(r, db, monkeypatch)
    assert logins == [("uzivatel", "heslo")] and ScriptedClient.calls[0]["token"] == "tok1"
    assert sec.k2s_token() == "tok1"                       # token se uloží, příště se nepřihlašuje znovu
    ScriptedClient.script = ["https://dl.example.test/f.rar"]
    run_job(r, db, monkeypatch)
    assert len(logins) == 1 and ScriptedClient.calls[-1]["token"] == "tok1"


def test_anonymous_when_no_login_is_set(rt, monkeypatch, tmp_path):
    from viddown.config import Secrets
    r, db = rt
    r.secrets = Secrets(tmp_path / "secrets.json")
    ScriptedClient.script = ["https://dl.example.test/f.rar"]
    run_job(r, db, monkeypatch)
    assert ScriptedClient.calls[0]["token"] is None


def test_clearing_login_also_drops_token(tmp_path):
    from viddown.config import Secrets
    sec = Secrets(tmp_path / "secrets.json")
    sec.set_k2s_login("a", "b")
    sec.set_k2s_token("t")
    sec.set_k2s_login("", "")
    assert sec.k2s_login() is None and sec.k2s_token() == ""


def test_settings_endpoint_saves_login_without_showing_password(data, tmp_path):
    from fastapi.testclient import TestClient
    from viddown.server import create_app
    from tests.test_api import State
    st = State(data)
    c = TestClient(create_app(st))
    assert c.post("/api/settings/k2s_login", json={"username": "u", "password": ""}).status_code == 400
    r = c.post("/api/settings/k2s_login", json={"username": "u", "password": "tajne"})
    assert r.status_code == 200 and r.json()["k2s_login_set"] is True
    assert "tajne" not in r.text
    r = c.post("/api/settings/k2s_login", json={"username": "", "password": ""})
    assert r.json()["k2s_login_set"] is False


def test_probe_accepts_keep2share_url_without_yt_dlp(data):
    from viddown import probe
    from viddown.resolvers import Ctx
    res = asyncio.run(probe.probe_url(URL, Ctx(Settings().all(), FakeEngines(), data)))
    assert res["type"] == "video" and res["method"] == "k2s" and res["title"] == "film.rar"


def test_captcha_answer_forms(rt):
    import asyncio as aio
    from viddown.telegram import TelegramBot
    r, db = rt
    bot = TelegramBot.__new__(TelegramBot)
    bot.runner = r
    sent = []

    async def fake_send(text, chat=None, **kw):
        sent.append(text)
    bot.send = fake_send
    bot._captcha_msgs = {555: 7}
    bot.lang = lambda: "cs"

    async def scenario():
        fut = aio.get_running_loop().create_future()
        r.k2s_waiters[7] = fut
        # 1) jen kód, když čeká jedna captcha
        assert await bot._captcha_answer({}, "GeMNSB") is True and fut.result() == "GeMNSB"
        fut2 = aio.get_running_loop().create_future()
        r.k2s_waiters[8] = fut2
        # 2) více čekajících: odpověď na zprávu s captchou
        assert await bot._captcha_answer({"reply_to_message": {"message_id": 555}}, "abc") is False   # položka 7 už má odpověď
        assert fut.result() == "GeMNSB"
        bot._captcha_msgs[556] = 8
        assert await bot._captcha_answer({"reply_to_message": {"message_id": 556}}, "abc") is True and fut2.result() == "abc"
        assert await bot._captcha_answer({}, "abc") is False      # nejednoznačné: nic nepřiřazuje
        # 3) prefix „#9 xyz“ (zároveň se nečeká na jinou položku)
        fut3 = aio.get_running_loop().create_future()
        r.k2s_waiters[9] = fut3
        assert await bot._captcha_answer({}, "#9 xyz") is True and fut3.result() == "xyz"
        # 4) běžné zprávy a adresy se nezachytí
        assert await bot._captcha_answer({}, "https://k2s.cc/file/abc/x.rar") is False
        assert await bot._captcha_answer({}, "/fronta") is False
        r.k2s_waiters.clear()
        return sent

    asyncio.run(scenario())


def test_captcha_send_failure_postpones_instead_of_failing(rt, monkeypatch):
    r, db = rt

    async def broken_sender(jid, img):
        raise RuntimeError("Telegram není připojen")

    r.captcha_sender = broken_sender
    ScriptedClient.script = [k2s.K2SError("captcha", 30, "captcha"), "https://dl.example.test/f.rar"]
    jid, res = run_job(r, db, monkeypatch)
    assert res["file"].read_bytes() == b"video-bytes"


def test_captcha_reply_ignores_addresses_without_scheme():
    from viddown.telegram import TelegramBot
    from viddown.resolvers import k2s as k
    r = runner_mod.Runner.__new__(runner_mod.Runner)
    r.k2s_waiters = {}
    fut = asyncio.new_event_loop().create_future()
    r.k2s_waiters[3] = fut
    bot = TelegramBot.__new__(TelegramBot)
    bot.runner = r
    bot._captcha_msgs = {}
    bot.lang = lambda: "cs"

    async def nosend(text, chat=None, **kw):
        return None
    bot.send = nosend
    assert asyncio.run(bot._captcha_answer({}, "youtube.com/watch?v=abc")) is False
    assert not fut.done()
    assert k.parse_captcha_reply("12 abc") == (12, "abc")


def test_changing_login_drops_old_token(tmp_path):
    from viddown.config import Secrets
    sec = Secrets(tmp_path / "secrets.json")
    sec.set_k2s_login("a", "b")
    sec.set_k2s_token("stary-token")
    sec.set_k2s_login("c", "d")
    assert sec.k2s_token() == "" and sec.k2s_login() == ("c", "d")


def test_password_without_username_is_rejected(data):
    from fastapi.testclient import TestClient
    from viddown.server import create_app
    from tests.test_api import State
    c = TestClient(create_app(State(data)))
    assert c.post("/api/settings/k2s_login", json={"username": "", "password": "x"}).status_code == 400


def test_wait_uses_time_wait_from_server(rt, monkeypatch, tmp_path):
    r, db = rt
    waits = []

    async def fake_sleep(job, holder, seconds, stage):
        waits.append(seconds)
    monkeypatch.setattr(r, "_k2s_sleep", fake_sleep)
    ScriptedClient.script = [k2s.K2SError("čeká", 41, "wait", wait_seconds=300), "https://dl.example.test/f.rar"]
    jid, res = run_job(r, db, monkeypatch)
    assert waits == [305.0] and res["file"].exists()
