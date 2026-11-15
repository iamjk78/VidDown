"""Zálohy jsou šifrované klíčem zabudovaným v aplikaci (otevřou se v jakékoli instalaci bez klíče); zálohy z verze 0.2.0
(klíč instalace) jdou dál obnovit."""
import os
import zipfile

import pytest

from tests.test_api import client  # noqa: F401
from tests.test_backup import make_data
from viddown import backup, dtb


def test_backup_opens_in_another_installation_without_any_key(data, tmp_path, monkeypatch):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "z.dtb")
    assert z.read_bytes()[:6] == dtb.MAGIC1 and not (data / "backup.key").exists()     # žádný klíč instalace nevzniká
    other = tmp_path / "jina"
    other.mkdir()
    monkeypatch.setenv("VIDDOWN_DATA", str(other))
    assert backup.validate(z)["jobs"] >= 1
    assert backup.stage(other, z) and dtb.is_dtb(other / "restore" / "pending.zip")
    assert backup.validate(other / "restore" / "pending.zip")


def v2_backup(src, dst, key):
    plain = backup.create(src, dst.with_suffix(".zip"), encrypt=False)
    dtb.encrypt_file(plain, dst, key)
    return dst


def test_backups_from_version_020_still_restore(data, tmp_path, monkeypatch):
    src = make_data(tmp_path / "a")
    k = dtb.install_key()                                              # instalace s verzí 0.2.0 má klíč v backup.key
    z = v2_backup(src, tmp_path / "z.dtb", k)
    assert z.read_bytes()[:6] == dtb.MAGIC2 and backup.validate(z)["jobs"] >= 1      # na stejné instalaci bez zadávání
    other = tmp_path / "jina"
    other.mkdir()
    monkeypatch.setenv("VIDDOWN_DATA", str(other))
    with pytest.raises(backup.KeyNeededError):
        backup.validate(z)
    assert backup.validate(z, dtb.format_key(k))["jobs"] >= 1


def test_key_format_roundtrip():
    k = os.urandom(32)
    assert dtb.parse_key(dtb.format_key(k)) == k and dtb.parse_key(dtb.format_key(k).lower().replace("-", " ")) == k
    for bad in ("", "abc", "AAAA-BBBB"):
        with pytest.raises(dtb.DtbError):
            dtb.parse_key(bad)


def test_key_file_is_never_inside_the_backup(data, tmp_path):
    src = make_data(tmp_path / "a")
    (src / "backup.key").write_text("00" * 32)
    z = backup.create(src, tmp_path / "z.zip", encrypt=False)
    assert "backup.key" not in zipfile.ZipFile(z).namelist()


def test_api_restore_of_a_foreign_020_backup_asks_for_its_key(client, tmp_path, monkeypatch):
    c, st = client
    other = make_data(tmp_path / "jina")
    k = os.urandom(32)
    z = v2_backup(other, tmp_path / "cizi.dtb", k)
    r = c.post("/api/restore", files={"file": ("cizi.dtb", open(z, "rb"), "application/octet-stream")})
    assert r.status_code == 400 and r.json()["detail"].startswith("KEY_NEEDED")
    r = c.post("/api/restore", files={"file": ("cizi.dtb", open(z, "rb"), "application/octet-stream")}, data={"key": dtb.format_key(k)})
    assert r.status_code == 200 and r.json()["manifest"]
