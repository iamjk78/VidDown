"""Logika Telegram bota s podvrženým Telegram API (bez sítě)."""
import asyncio

import pytest

from viddown.config import Secrets, Settings
from viddown.db import DB
from viddown.runner import Runner
from viddown.telegram import TelegramBot


class FakeEngines:
    def status(self):
        return [{"name": "yt-dlp", "current": "2026.10.26", "system": None}]


@pytest.fixture()
def bot(data, tmp_path):
    s = Settings()
    s.update({"telegram_chat_id": "42", "download_dir": str(tmp_path)})
    db = DB(data / "t.db")
    r = Runner(db, s, FakeEngines(), data)
    b = TelegramBot(r, db, s, Secrets(), FakeEngines())
    b.state = "ok"
    b.sent = []

    async def call(method, http_timeout=30, **p):
        b.sent.append((method, p))
        return {"message_id": 100 + len(b.sent)}
    b.call = call
    return b


def msg(text, chat=42):
    return {"update_id": 1, "message": {"message_id": 7, "chat": {"id": chat, "type": "private"}, "text": text}}


def test_foreign_chat_gets_its_id_only(bot):
    asyncio.run(bot.handle(msg("https://youtu.be/x", chat=999)))
    assert bot.sent[0][0] == "sendMessage" and "999" in bot.sent[0][1]["text"]
    assert bot.db.queue() == []


def test_url_is_queued_with_probing_reply(bot):
    asyncio.run(bot.handle(msg("stáhni https://youtu.be/abc prosím")))
    job = bot.db.queue()[0]
    assert job["url"] == "https://youtu.be/abc" and job["source"] == "telegram" and job["tg_chat"] == "42"
    assert "Zjišťuji" in bot.sent[0][1]["text"]


def test_probe_reply_and_confirm_buttons(bot):
    jid, _ = bot.runner.add("https://youtu.be/abc", source="telegram", tg_chat="42", tg_msg="5")
    job = bot.db.get(jid)
    bot.runner.apply_probe(dict(job, status="probing"), {"type": "video", "method": "ytdlp", "title": "Video", "height": 1080, "count": 1, "info": {}})
    asyncio.run(bot.on_probe(bot.db.get(jid), {"type": "video", "height": 1080, "count": 1}))
    method, p = bot.sent[-1]
    assert method == "editMessageText" and "1080p" in p["text"] and "Přidáno do fronty" in p["text"]

    bot.settings.update({"telegram_after_probe": "ask"})
    jid2, _ = bot.runner.add("https://youtu.be/def", source="telegram", tg_chat="42", tg_msg="6")
    bot.runner.apply_probe(dict(bot.db.get(jid2), status="probing"), {"type": "video", "method": "ytdlp", "title": "V2", "height": 720, "count": 1, "info": {}})
    assert bot.db.get(jid2)["status"] == "confirm"
    asyncio.run(bot.on_probe(bot.db.get(jid2), {"type": "video", "height": 720, "count": 1}))
    kb = bot.sent[-1][1]["reply_markup"]["inline_keyboard"][0]
    assert kb[0]["callback_data"] == f"ok:{jid2}"
    cb = {"update_id": 2, "callback_query": {"id": "q", "data": f"ok:{jid2}", "message": {"message_id": 6, "chat": {"id": 42}, "text": "V2\n…"}}}
    asyncio.run(bot.handle(cb))
    assert bot.db.get(jid2)["status"] == "queued"


def test_playlist_summary_text(bot):
    parent = {"id": 1, "title": "Kurz", "url": "https://x"}
    failed = [{"title": "Díl 3", "url": "https://x/3", "error": "Video unavailable"}]
    asyncio.run(bot.on_summary(parent, failed, 12))
    t = bot.sent[-1][1]["text"]
    assert "Kurz" in t and "1 z 12" in t and "Díl 3" in t


def test_commands(bot):
    asyncio.run(bot.handle(msg("/fronta")))
    assert "prázdná" in bot.sent[-1][1]["text"]
    asyncio.run(bot.handle(msg("/engine")))
    assert "yt-dlp: 2026.10.26" in bot.sent[-1][1]["text"]
    asyncio.run(bot.handle(msg("ahoj")))
    assert "odkaz" in bot.sent[-1][1]["text"]


def test_getupdates_timeout_param_does_not_clash(data):
    """Telegram long-polling posílá parametr 'timeout' – nesmí kolidovat s HTTP limitem volání."""
    import inspect
    sig = inspect.signature(TelegramBot.call)
    assert "timeout" not in sig.parameters
