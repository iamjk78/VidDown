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


# ---------------------------------------------------------------- migrace schématu
def test_fresh_db_gets_latest_schema_version(tmp_path):
    from viddown import db as dbm
    d = dbm.DB(tmp_path / "a.db")
    assert d.schema_version == dbm.MIGRATIONS[-1][0]
    assert d.migrate() == []          # druhé spuštění nic nedělá
    assert not list(tmp_path.glob("*.bak"))


def test_legacy_db_without_version_is_adopted(tmp_path):
    import sqlite3
    from viddown import db as dbm
    p = tmp_path / "legacy.db"
    c = sqlite3.connect(p)
    c.executescript(dbm.SCHEMA)       # databáze z doby před migracemi: tabulky jsou, user_version = 0
    c.execute("insert into jobs(url,pos,created_at,updated_at) values('https://x',1,1,1)")
    c.commit()
    c.close()
    d = dbm.DB(p)
    assert d.schema_version == dbm.MIGRATIONS[-1][0]
    assert d.query("select url from jobs")[0]["url"] == "https://x"


def test_new_migration_runs_with_backup_and_keeps_data(tmp_path, monkeypatch):
    from viddown import db as dbm
    p = tmp_path / "m.db"
    d = dbm.DB(p)
    jid = d.add("https://x")
    monkeypatch.setattr(dbm, "MIGRATIONS", dbm.MIGRATIONS + [(dbm.MIGRATIONS[-1][0] + 1, "alter table jobs add column note text;")])
    d2 = dbm.DB(p)
    assert d2.schema_version == dbm.MIGRATIONS[-1][0]
    d2.update(jid, note="ahoj")
    assert d2.get(jid)["note"] == "ahoj"
    bak = tmp_path / f"m.db.v{len(dbm.MIGRATIONS) - 1}.bak"
    assert bak.exists()               # záloha stavu před migrací, bez nového sloupce
    import sqlite3
    cols = [r[1] for r in sqlite3.connect(bak).execute("pragma table_info(jobs)")]
    assert "note" not in cols


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    import pytest
    from viddown import db as dbm
    p = tmp_path / "f.db"
    dbm.DB(p).add("https://x")
    bad = "alter table jobs add column ok_col text; alter table nonexistent add column z text;"
    monkeypatch.setattr(dbm, "MIGRATIONS", dbm.MIGRATIONS + [(dbm.MIGRATIONS[-1][0] + 1, bad)])
    with pytest.raises(Exception):
        dbm.DB(p)
    monkeypatch.undo()
    d = dbm.DB(p)
    assert d.schema_version == dbm.MIGRATIONS[-1][0]   # neúspěšná migrace se vrátila zpět, zůstala poslední platná verze
    assert "ok_col" not in [r["name"] for r in d.query("pragma table_info(jobs)")]
    assert len(d.query("select * from jobs")) == 1


def test_db_from_newer_version_is_refused(tmp_path):
    import sqlite3
    import pytest
    from viddown import db as dbm
    p = tmp_path / "n.db"
    dbm.DB(p)
    c = sqlite3.connect(p)
    c.execute("pragma user_version=99")
    c.close()
    with pytest.raises(dbm.SchemaTooNew):
        dbm.DB(p)


def test_remap_paths(tmp_path):
    from viddown import db as dbm
    d = dbm.DB(tmp_path / "r.db")
    a = d.add("https://a", status="done", filepath="/nas/Videos/x/a.mkv")
    b = d.add("https://b", status="done", filepath="/nas/Videos2/b.mkv")   # jiná složka, stejný začátek
    assert d.remap_paths("/nas/Videos/", "/downloads", dry_run=True) == 1
    assert d.remap_paths("/nas/Videos", "/downloads") == 1
    assert d.get(a)["filepath"] == "/downloads/x/a.mkv"
    assert d.get(b)["filepath"] == "/nas/Videos2/b.mkv"
