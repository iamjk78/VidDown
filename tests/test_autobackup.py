"""Automatické zálohy: rozvrh, uchování nejvýš N souborů, bezpečné mazání, chyby, API a nastavení."""
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_backup import make_data
from tests.test_subscriptions import State, rt  # noqa: F401
from viddown import autobackup as ab
from viddown import backup
from viddown.config import Settings
from viddown.db import DB
from viddown.server import create_app


class Bot:
    def __init__(self):
        self.sent = []

    def notify_threadsafe(self, key, **kw):
        self.sent.append((key, kw))


class St:
    """Co autobackup.run potřebuje: data, nastavení, databázi (kv) a bota."""
    def __init__(self, data, settings, bot=None):
        self.data, self.settings, self.bot = data, settings, bot
        self.db = DB(Path(data) / "viddown.db")


@pytest.fixture
def env(data, tmp_path):
    make_data(data)
    dest = tmp_path / "zalohy"
    s = Settings()
    s.update({"auto_backup": True, "auto_backup_dir": str(dest), "auto_backup_keep": 3, "auto_backup_hours": 24})
    return St(data, s, Bot()), dest


def age(dest, steps=1):
    """Zálohy mají rozlišitelné časy změny (stejná sekunda by nešla seřadit)."""
    files = sorted(dest.glob("*.dtb"), key=lambda p: p.stat().st_mtime_ns)
    for i, p in enumerate(files):
        os.utime(p, (1_700_000_000 + i * 10, 1_700_000_000 + i * 10))


def test_run_creates_verified_encrypted_backup(env):
    st, dest = env
    res = ab.run(st)
    assert ab.NAME_RE.match(res["file"]) and (dest / res["file"]).is_file()
    assert (dest / res["file"]).read_bytes().startswith(b"VDDTB")
    assert backup.validate(dest / res["file"])["jobs"] == 1
    s = ab.state(st.db)
    assert s["error"] is None and s["file"] == res["file"] and s["dir"] == str(dest)
    assert not list(dest.glob("*.enc")) and not list(dest.glob("*.part"))


def test_keeps_only_n_and_deletes_oldest_after_success(env, monkeypatch):
    st, dest = env
    minutes = iter(range(10, 20))
    monkeypatch.setattr(backup, "default_name", lambda encrypt=True: f"VidDown_2026-11-13_19-{next(minutes)}.dtb")
    names = []
    for i in range(5):
        names.append(ab.run(st)["file"])
        os.utime(dest / names[-1], (1_800_000_000 + i, 1_800_000_000 + i))      # čas změny roste s pořadím záloh
    assert [b["name"] for b in ab.list_backups(dest)] == names[:1:-1]            # zůstaly 3 nejnovější, nejnovější první
    assert not any((dest / n).exists() for n in names[:2])


def test_prune_touches_only_our_files_and_keeps_new_one(tmp_path):
    fold = tmp_path / "f"
    fold.mkdir()
    ours = [f"VidDown_2026-01-0{i}_10-00.dtb" for i in range(1, 6)]
    others = ["foto.jpg", "VidDown_poznamky.txt", "VidDown_2026-01-01_10-00.dtb.bak", "VidDown_2026-01-01_10-00.zip"]
    for i, n in enumerate(ours + others):
        (fold / n).write_text("x")
        os.utime(fold / n, (1_700_000_000 + i, 1_700_000_000 + i))
    new = fold / ours[0]                                    # „nová“ záloha je podle času nejstarší, přesto se nesmaže
    removed = ab.prune(fold, 2, new)
    assert new.exists() and len(removed) == 3
    assert all((fold / n).exists() for n in others)         # cizí soubory zůstaly
    assert len(ab.list_backups(fold)) == 2
    assert ab.prune(fold, 1, new) == [ab.list_backups(fold)[0]["name"]] or len(ab.list_backups(fold)) == 1


def test_failure_deletes_nothing_and_notifies_once(env, monkeypatch):
    st, dest = env
    ab.run(st)
    age(dest)
    before = {b["name"] for b in ab.list_backups(dest)}

    def boom(*a, **k):
        raise OSError("Síťová složka není dostupná")
    monkeypatch.setattr(backup, "create", boom)
    for _ in range(2):
        with pytest.raises(backup.BackupError, match="není dostupná"):
            ab.run(st)
    assert {b["name"] for b in ab.list_backups(dest)} == before
    s = ab.state(st.db)
    assert "není dostupná" in s["error"] and s["last_ok"] > 0                    # poslední úspěch zůstal
    assert [k for k, _ in st.bot.sent] == ["backup_fail"]                       # zpráva jen jednou


def test_unreadable_new_backup_is_discarded_and_old_ones_kept(env, monkeypatch):
    st, dest = env
    first = ab.run(st)["file"]
    age(dest)

    def bad(path):
        raise backup.BackupError("poškozená")
    monkeypatch.setattr(backup, "validate", bad)
    with pytest.raises(backup.BackupError):
        ab.run(st)
    assert [b["name"] for b in ab.list_backups(dest)] == [first]


def test_due_schedule_retry_and_folder_change(env):
    st, dest = env
    s, db, now = st.settings, st.db, time.time()
    assert ab.due(s, db, now)                               # ještě nikdy nezálohováno
    ab.run(st)
    assert not ab.due(s, db, now + 3600 * 23) and ab.due(s, db, now + 3600 * 25)
    s.update({"auto_backup_hours": 6})
    assert ab.due(s, db, now + 3600 * 7)
    s.update({"auto_backup_hours": 24, "auto_backup_dir": str(dest.parent / "jina")})
    assert ab.due(s, db, now + 60)                          # nová složka = zálohovat hned
    s.update({"auto_backup": False})
    assert not ab.due(s, db, now + 10 ** 7) and ab.next_due(s, db) is None
    # po chybě se další pokus odloží o hodinu
    s.update({"auto_backup": True})
    db.kv_set(ab.KV, {"last_ok": 0, "last_try": now, "error": "x", "dir": str(ab.folder(st.data, s))})
    assert not ab.due(s, db, now + 600) and ab.due(s, db, now + 3601)


def test_stale_leftovers_are_cleaned_but_fresh_ones_stay(env):
    st, dest = env
    dest.mkdir(parents=True)
    old, fresh, other = dest / "VidDown_x.dtb.enc", dest / "VidDown_y.dtb.part", dest / "cizi.enc"
    for p in (old, fresh, other):
        p.write_text("x")
    os.utime(old, (1_600_000_000, 1_600_000_000))
    os.utime(other, (1_600_000_000, 1_600_000_000))
    ab.run(st)
    assert not old.exists() and fresh.exists() and other.exists()


def test_two_backups_in_the_same_minute_get_distinct_names(env):
    st, dest = env
    a, b, c = ab.run(st)["file"], ab.run(st)["file"], ab.run(st)["file"]
    assert len({a, b, c}) == 3 and all(ab.NAME_RE.match(x) for x in (a, b, c))


def test_tick_runs_only_when_due(env):
    st, dest = env
    ab.tick(st)
    assert len(ab.list_backups(dest)) == 1
    ab.tick(st)
    assert len(ab.list_backups(dest)) == 1                  # ještě není na řadě
    st.settings.update({"auto_backup": False})
    st.db.kv_set(ab.KV, {})
    ab.tick(st)
    assert len(ab.list_backups(dest)) == 1                  # vypnuto


def test_default_folder_is_backups_in_data_dir(data):
    s = Settings()
    assert ab.folder(data, s) == data / "backups"


def test_settings_validation(data):
    s = Settings()
    for k, v in (("auto_backup_hours", 5), ("auto_backup_keep", 0), ("auto_backup_keep", 101)):
        with pytest.raises(ValueError):
            s.update({k: v})
    assert s.update({"auto_backup_hours": 168, "auto_backup_keep": 10})["auto_backup_hours"] == 168


# ------------------------------------------------------------ API
def client_for(rt, data, monkeypatch):
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    make_data(data)
    return TestClient(create_app(State(rt, data)))


def test_api_status_run_list_and_restore_from_folder(rt, data, tmp_path, monkeypatch):
    c = client_for(rt, data, monkeypatch)
    dest = tmp_path / "ab"
    r = c.put("/api/settings", json={"auto_backup": True, "auto_backup_dir": str(dest), "auto_backup_keep": 2})
    assert r.status_code == 200
    st = c.get("/api/autobackup").json()
    assert st["enabled"] and st["dir"] == str(dest) and st["backups"] == [] and st["keep"] == 2
    run = c.post("/api/autobackup/run")
    assert run.status_code == 200
    j = run.json()
    assert len(j["backups"]) == 1 and j["state"]["error"] is None and j["next"] > time.time()
    name = j["backups"][0]["name"]
    ok = c.post("/api/autobackup/restore", json={"name": name})
    assert ok.status_code == 200 and ok.json()["manifest"]["jobs"] == 1
    assert c.get("/api/restore").json()["pending"]["manifest"]["jobs"] == 1
    for bad in ("../x.dtb", "foto.jpg", "VidDown_2020-01-01_00-00.dtb"):
        assert c.post("/api/autobackup/restore", json={"name": bad}).status_code == 404


def test_api_settings_reject_bad_values_and_unwritable_folder(rt, data, tmp_path, monkeypatch):
    c = client_for(rt, data, monkeypatch)
    assert c.put("/api/settings", json={"auto_backup_hours": 5}).status_code == 400
    assert c.put("/api/settings", json={"auto_backup_keep": 0}).status_code == 400
    f = tmp_path / "soubor"
    f.write_text("x")
    assert c.put("/api/settings", json={"auto_backup_dir": str(f / "pod")}).status_code == 400
    assert c.put("/api/settings", json={"auto_backup_dir": ""}).status_code == 200      # prázdné = výchozí složka


def test_api_run_reports_error_when_folder_missing(rt, data, tmp_path, monkeypatch):
    c = client_for(rt, data, monkeypatch)
    dest = tmp_path / "nas"
    assert c.put("/api/settings", json={"auto_backup_dir": str(dest)}).status_code == 200
    monkeypatch.setattr(backup, "create", lambda *a, **k: (_ for _ in ()).throw(OSError("NAS není připojený")))
    r = c.post("/api/autobackup/run")
    assert r.status_code == 400 and "NAS není připojený" in r.json()["detail"]
    assert c.get("/api/autobackup").json()["state"]["error"]
