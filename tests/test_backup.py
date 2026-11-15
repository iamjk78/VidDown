"""Záloha a obnova dat (export a import): modul, čekající obnova při startu, API a CLI."""
import asyncio
import json
import os
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_subscriptions import State, rt  # noqa: F401  (fixture rt)
from viddown import backup, dtb
from viddown.db import DB, MIGRATIONS
from viddown.server import create_app


def make_data(root: Path, paths=("/nas/Videa",), token="123:ABC") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    db = DB(root / "viddown.db")
    for i, base in enumerate(paths):
        db.add(f"https://x/{i}", status="done", filepath=f"{base}/v{i}.mp4", target_dir=base)
    db.sub_add(url="https://x/chan", kind="channel", title="Kanál", folder=f"{paths[0]}/odber")
    (root / "settings.json").write_text(json.dumps({"download_dir": paths[0], "temp_dir": ""}), "utf-8")
    (root / "secrets.json").write_text(json.dumps({"telegram_token": token}), "utf-8")
    (root / "cookies.txt").write_text("# cookies\n", "utf-8")
    (root / "archive.txt").write_text("youtube abc\n", "utf-8")
    (root / "thumbs").mkdir(exist_ok=True)
    (root / "thumbs" / "t.jpg").write_bytes(b"jpg")
    (root / "engines").mkdir(exist_ok=True)
    (root / "engines" / "big.bin").write_bytes(b"x" * 1000)
    (root / "logs").mkdir(exist_ok=True)
    (root / "logs" / "a.log").write_text("log")
    return root


def names(p):
    with zipfile.ZipFile(p) as z:
        return set(z.namelist())


def test_backup_contains_only_what_is_needed(tmp_path):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "b.zip", encrypt=False)
    assert names(z) == {"backup.json", "viddown.db", "settings.json", "secrets.json", "cookies.txt", "archive.txt"}
    z2 = backup.create(src, tmp_path / "c.zip", include_thumbs=True, encrypt=False)
    assert "thumbs/t.jpg" in names(z2) and not any(n.startswith(("engines", "logs")) for n in names(z2))
    man = backup.validate(z)
    assert man["jobs"] == 1 and man["done"] == 1 and man["subscriptions"] == 1
    assert man["schema_version"] == MIGRATIONS[-1][0] and man["path_hint"] == "/nas/Videa"
    assert man["download_dir"] == "/nas/Videa"
    assert man["files"] == ["settings.json", "secrets.json", "cookies.txt", "archive.txt"]


def test_backup_roundtrip_to_another_machine(tmp_path):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "b.zip", include_thumbs=True)
    dst = tmp_path / "novy"
    dst.mkdir()
    res = backup.apply(dst, z)
    assert res["ok"]
    db = DB(dst / "viddown.db")
    assert len(db.query("select * from jobs")) == 1 and len(db.query("select * from subscriptions")) == 1
    assert json.loads((dst / "secrets.json").read_text())["telegram_token"] == "123:ABC"
    assert (dst / "archive.txt").read_text() == "youtube abc\n" and (dst / "thumbs" / "t.jpg").exists()
    assert (os.stat(dst / "secrets.json").st_mode & 0o777) == 0o600


def test_backup_is_consistent_while_database_is_open_and_in_wal(tmp_path):
    src = make_data(tmp_path / "a")
    db = DB(src / "viddown.db")                    # otevřená databáze v režimu WAL
    for i in range(50):
        db.add(f"https://x/w{i}")
    z = backup.create(src, tmp_path / "b.zip")
    dst = tmp_path / "n"
    dst.mkdir()
    backup.apply(dst, z)
    assert len(DB(dst / "viddown.db").query("select * from jobs")) == 51


def test_validate_rejects_bad_backups(tmp_path):
    src = make_data(tmp_path / "a")
    good = backup.create(src, tmp_path / "good.zip", encrypt=False)
    notzip = tmp_path / "x.zip"
    notzip.write_text("nic")
    with pytest.raises(backup.BackupError, match="není platná"):
        backup.validate(notzip)

    def mutate(name, fn):
        out = tmp_path / name
        with zipfile.ZipFile(good) as zi, zipfile.ZipFile(out, "w") as zo:
            for n in zi.namelist():
                data = zi.read(n)
                r = fn(n, data)
                if r is not None:
                    zo.writestr(n, r)
            fn(None, None)
        return out

    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(good) as zi, zipfile.ZipFile(extra, "w") as zo:
        for n in zi.namelist():
            zo.writestr(n, zi.read(n))
        zo.writestr("evil.sh", "rm -rf /")
    with pytest.raises(backup.BackupError, match="nečekaný"):
        backup.validate(extra)
    trav = tmp_path / "trav.zip"
    with zipfile.ZipFile(good) as zi, zipfile.ZipFile(trav, "w") as zo:
        for n in zi.namelist():
            zo.writestr(n, zi.read(n))
        zo.writestr("thumbs/../../x", "x")
    with pytest.raises(backup.BackupError, match="nečekaný"):
        backup.validate(trav)
    nomani = mutate("nomani.zip", lambda n, d: None if n == "backup.json" else d)
    with pytest.raises(backup.BackupError, match="backup.json"):
        backup.validate(nomani)
    newer_fmt = mutate("newfmt.zip", lambda n, d: json.dumps({**json.loads(d), "format": 99}) if n == "backup.json" else d)
    with pytest.raises(backup.BackupError, match="novější verze VidDown"):
        backup.validate(newer_fmt)


def test_validate_rejects_newer_schema_and_corrupt_db(tmp_path):
    src = make_data(tmp_path / "a")
    snap = tmp_path / "snap.db"
    sqlite3.connect(src / "viddown.db").backup(sqlite3.connect(snap))
    c = sqlite3.connect(snap)
    c.execute(f"pragma user_version={MIGRATIONS[-1][0] + 5}")
    c.commit()
    c.close()
    z = tmp_path / "newer.zip"
    with zipfile.ZipFile(z, "w") as zo:
        zo.writestr("backup.json", json.dumps({"format": 1}))
        zo.write(snap, "viddown.db")
    with pytest.raises(backup.BackupError, match="novější verze"):
        backup.validate(z)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zo:
        zo.writestr("backup.json", json.dumps({"format": 1}))
        zo.writestr("viddown.db", b"tohle neni databaze" * 100)
    with pytest.raises(backup.BackupError, match="poškozená"):
        backup.validate(bad)


def test_apply_keeps_previous_state_and_prunes(tmp_path, monkeypatch):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "b.zip")
    dst = make_data(tmp_path / "dst", paths=("/stary",), token="STARY")
    times = iter(range(100, 200))
    monkeypatch.setattr(backup.time, "strftime", lambda f: f"2026{next(times):04d}")
    for _ in range(5):
        res = backup.apply(dst, z)
    before = sorted((dst / "restore").glob("before-*"))
    assert len(before) == backup.KEEP_BEFORE
    # první obnova uložila stav „STARY“; po pěti obnovách zůstaly jen poslední tři (už ze zálohy)
    assert json.loads((Path(res["before"]) / "secrets.json").read_text())["telegram_token"] == "123:ABC"
    first = tmp_path / "dst2"
    first.mkdir()
    old = make_data(first, paths=("/stary",), token="STARY")
    r = backup.apply(old, z)
    assert json.loads((Path(r["before"]) / "secrets.json").read_text())["telegram_token"] == "STARY"
    c = sqlite3.connect(Path(r["before"]) / "viddown.db")
    assert c.execute("select filepath from jobs").fetchone()[0].startswith("/stary/")
    c.close()


def test_remap_paths_respects_boundaries(tmp_path):
    src = make_data(tmp_path / "a", paths=("/nas/Videa", "/nas/Videa2"))
    z = backup.create(src, tmp_path / "b.zip")
    dst = tmp_path / "n"
    dst.mkdir()
    res = backup.apply(dst, z, ("/nas/Videa/", "/downloads"))
    assert res["remap"] == {"filepath": 1, "target_dir": 1, "folder": 1, "settings": 1}
    c = sqlite3.connect(dst / "viddown.db")
    assert sorted(r[0] for r in c.execute("select filepath from jobs")) == ["/downloads/v0.mp4", "/nas/Videa2/v1.mp4"]
    assert c.execute("select folder from subscriptions").fetchone()[0] == "/downloads/odber"
    c.close()
    assert json.loads((dst / "settings.json").read_text())["download_dir"] == "/downloads"


def test_pending_restore_is_applied_at_start_and_reports_result(tmp_path):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "b.zip")
    dst = make_data(tmp_path / "dst", paths=("/stary",), token="STARY")
    man = backup.stage(dst, z)
    assert man["jobs"] == 1 and backup.pending(dst)["manifest"]["jobs"] == 1
    assert json.loads((dst / "secrets.json").read_text())["telegram_token"] == "STARY"     # zatím se nic nezměnilo
    backup.set_remap(dst, "/nas/Videa", "/downloads")
    res = backup.apply_pending(dst)
    assert res["ok"] and backup.pending(dst) is None and backup.last_result(dst)["ok"]
    assert json.loads((dst / "secrets.json").read_text())["telegram_token"] == "123:ABC"
    assert DB(dst / "viddown.db").query("select filepath from jobs")[0]["filepath"] == "/downloads/v0.mp4"
    assert backup.apply_pending(dst) is None


def test_broken_pending_restore_keeps_old_data(tmp_path):
    dst = make_data(tmp_path / "dst", paths=("/stary",), token="STARY")
    d = dst / "restore"
    d.mkdir()
    (d / "pending.zip").write_text("rozbité")
    (d / "pending.json").write_text(json.dumps({"manifest": None, "remap": None}))
    res = backup.apply_pending(dst)
    assert res["ok"] is False and backup.pending(dst) is None and not backup.last_result(dst)["ok"]
    assert json.loads((dst / "secrets.json").read_text())["telegram_token"] == "STARY"
    assert len(DB(dst / "viddown.db").query("select * from jobs")) == 1


def test_set_remap_requires_pending(tmp_path):
    with pytest.raises(backup.BackupError):
        backup.set_remap(tmp_path, "/a", "/b")


# ------------------------------------------------------------ API
def make_client(rt, data):
    st = State(rt, data)
    st.stop = asyncio.Event()
    st.restart = False
    return TestClient(create_app(st)), st


def test_api_backup_download_and_restore_flow(rt, data, monkeypatch):
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    DB(data / "viddown.db").add("https://x/a", status="done", filepath="/nas/Videa/a.mp4")   # skutečná databáze aplikace
    c, st = make_client(rt, data)
    r = c.get("/api/backup")
    assert r.status_code == 200 and r.content.startswith(dtb.MAGIC)          # výchozí: šifrovaný .dtb
    assert re.search(r'filename="VidDown_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.dtb"', r.headers["content-disposition"])
    z = Path(data) / "dl.dtb"
    z.write_bytes(r.content)
    plain = c.get("/api/backup?plain=1")
    assert plain.status_code == 200 and plain.headers["content-type"] == "application/zip" and ".zip" in plain.headers["content-disposition"]
    zp = Path(data) / "dl.zip"
    zp.write_bytes(plain.content)
    assert "viddown.db" in names(zp)
    assert c.get("/api/restore").json() == {"pending": None, "last": None}
    # import: nahrání → ověření → čeká na potvrzení
    up = c.post("/api/restore", files={"file": ("VidDown.dtb", z.read_bytes(), "application/octet-stream")})
    assert up.status_code == 200 and up.json()["manifest"]["done"] == 1
    assert c.get("/api/restore").json()["pending"]["manifest"]["done"] == 1
    ap = c.post("/api/restore/apply", json={"remap_old": "/nas/Videa", "remap_new": "/downloads"})
    assert ap.status_code == 200 and st.restart is True
    assert backup.pending(data)["remap"] == ["/nas/Videa", "/downloads"]
    assert c.delete("/api/restore").json()["pending"] is None


def test_api_restore_rejects_garbage_and_apply_without_pending(rt, data, monkeypatch):
    monkeypatch.setenv("VIDDOWN_ALLOW_NO_PASSWORD", "1")
    c, st = make_client(rt, data)
    r = c.post("/api/restore", files={"file": ("x.zip", b"nic", "application/zip")})
    assert r.status_code == 400 and "není platná" in r.json()["detail"]
    assert c.post("/api/restore/apply", json={}).status_code == 409
    assert st.restart is False


# ------------------------------------------------------------ CLI
def test_cli_backup_and_restore(tmp_path, monkeypatch, capsys):
    from viddown import cli
    src = make_data(tmp_path / "a")
    monkeypatch.setenv("VIDDOWN_DATA", str(src))
    z = tmp_path / "out.zip"
    assert cli.main(["backup", str(z)]) == 0
    assert "Pozor" in capsys.readouterr().out and z.exists()
    dst = tmp_path / "novy"
    monkeypatch.setenv("VIDDOWN_DATA", str(dst))
    monkeypatch.setattr("viddown.daemon.running_info", lambda: None)
    assert cli.main(["restore", str(z), "--yes", "--remap", "/nas/Videa", "/downloads"]) == 0    # jiná instalace, žádný klíč
    out = capsys.readouterr().out
    assert "Obnoveno" in out and "filepath 1" in out
    assert DB(dst / "viddown.db").query("select filepath from jobs")[0]["filepath"] == "/downloads/v0.mp4"
    assert cli.main(["restore", str(tmp_path / "neexistuje.zip"), "--yes"]) == 1


def test_cli_restore_while_running_only_stages(tmp_path, monkeypatch, capsys):
    from viddown import cli
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "out.zip")
    dst = make_data(tmp_path / "b", paths=("/stary",), token="STARY")
    monkeypatch.setenv("VIDDOWN_DATA", str(dst))
    monkeypatch.setattr("viddown.daemon.running_info", lambda: {"pid": 1})
    assert cli.main(["restore", str(z)]) == 0
    assert "při jejím dalším startu" in capsys.readouterr().out
    assert backup.pending(dst) is not None
    assert json.loads((dst / "secrets.json").read_text())["telegram_token"] == "STARY"
