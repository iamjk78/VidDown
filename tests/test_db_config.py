import json

import pytest

from viddown.config import Secrets, Settings
from viddown.db import DB


def test_queue_order_children_and_move(data):
    db = DB(data / "t.db")
    a = db.add("https://a", status="queued")
    p = db.add("https://playlist", status="expanded", kind="playlist")
    b = db.add("https://b", status="queued")
    kids = db.add_children(p, [{"url": f"https://k{i}"} for i in range(3)], "Složka", "gui")
    order = [j["url"] for j in db.queue()]
    assert order == ["https://a", "https://playlist", "https://k0", "https://k1", "https://k2", "https://b"]
    db.move(b, a)  # b před a
    assert [j["url"] for j in db.queue()][:2] == ["https://b", "https://a"]
    db.move(p, b)  # playlist i s dětmi na začátek
    assert [j["url"] for j in db.queue()][:4] == ["https://playlist", "https://k0", "https://k1", "https://k2"]
    assert all(db.get(k)["subdir"] == "Složka" for k in kids)


def test_recover_and_history(data):
    db = DB(data / "t.db")
    r = db.add("https://r", status="running")
    pr = db.add("https://p", status="probing")
    d = db.add("https://d", status="done", title="Hotové")
    db.recover()
    assert db.get(r)["status"] == "queued" and db.get(pr)["status"] == "new"
    assert [h["id"] for h in db.history()] == [d]
    assert db.history(q="Hot")[0]["id"] == d
    assert db.delete_history([d]) == 1


def test_find_active_url_dedup(data):
    db = DB(data / "t.db")
    j = db.add("https://x", status="queued")
    assert db.find_active_url("https://x")["id"] == j
    db.update(j, status="done")
    assert db.find_active_url("https://x") is None


def test_settings_types_choices_and_env(data, monkeypatch):
    s = Settings()
    assert s["concurrency"] == 2
    s.update({"concurrency": "4", "schedule_start": "7:5", "channel_tabs": "videos,shorts", "rate_limit_enabled": "ano"})
    v = s.all()
    assert v["concurrency"] == 4 and v["schedule_start"] == "07:05" and v["channel_tabs"] == ["videos", "shorts"]
    assert v["rate_limit_enabled"] is True
    with pytest.raises(ValueError):
        s.update({"quality": "nejlepší"})
    with pytest.raises(ValueError):
        s.update({"neexistuje": 1})
    monkeypatch.setenv("VIDDOWN_CONCURRENCY", "7")
    assert s["concurrency"] == 7 and "concurrency" in s.locked_keys()
    raw = json.loads((data / "settings.json").read_text())
    assert raw["concurrency"] == 4


def test_secrets_password(data):
    sec = Secrets()
    assert not sec.has_password()
    sec.set_password("tajne123")
    assert sec.has_password() and sec.check_password("tajne123") and not sec.check_password("spatne")
    assert "tajne123" not in (data / "secrets.json").read_text()
    sec.set_password("")
    assert not sec.has_password()
