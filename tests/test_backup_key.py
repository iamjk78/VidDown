"""Klíč záloh instalace: záloha z jiné instalace potřebuje její klíč, starší zálohy (v1) jdou dál obnovit, klíč není v záloze."""
import os
import zipfile

import pytest

from tests.test_api import client  # noqa: F401
from tests.test_backup import make_data
from viddown import backup, dtb


def legacy_encrypt(src, dst):
    """Záloha ve starém formátu v1 (klíč zabudovaný v aplikaci)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, prefix = os.urandom(16), os.urandom(4)
    header = dtb.MAGIC1 + salt + prefix
    aes = AESGCM(dtb._derive(dtb._LEGACY, salt, b"VidDown backup v1"))
    ct = aes.encrypt(prefix + (0).to_bytes(8, "big"), src.read_bytes(), header + (0).to_bytes(8, "big") + b"\x01")
    dst.write_bytes(header + len(ct).to_bytes(4, "big") + ct)


def test_key_format_roundtrip_and_validation(data):
    k = dtb.install_key()
    assert dtb.install_key() == k and len(k) == 32 and oct((data / "backup.key").stat().st_mode)[-3:] == "600"
    txt = dtb.format_key(k)
    assert dtb.parse_key(txt) == k and dtb.parse_key(txt.lower().replace("-", " ")) == k
    for bad in ("", "abc", "AAAA-BBBB"):
        with pytest.raises(dtb.DtbError):
            dtb.parse_key(bad)


def test_backup_from_another_installation_needs_its_key(data, tmp_path, monkeypatch):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "z.dtb")
    key = dtb.format_key(dtb.install_key())
    assert z.read_bytes()[:6] == dtb.MAGIC2
    other = tmp_path / "jina"
    other.mkdir()
    monkeypatch.setenv("VIDDOWN_DATA", str(other))                  # nová instalace = jiný klíč
    with pytest.raises(backup.KeyNeededError):
        backup.validate(z)
    assert backup.validate(z, key)["jobs"] >= 1
    man = backup.stage(other, z, key)
    assert man and dtb.is_dtb(other / "restore" / "pending.zip")          # připravená obnova je šifrovaná klíčem nové instalace
    assert backup.validate(other / "restore" / "pending.zip")            # a otevře se bez zadávání klíče


def test_old_v1_backups_still_restore(data, tmp_path):
    src = make_data(tmp_path / "a")
    plain = backup.create(src, tmp_path / "z.zip", encrypt=False)
    old = tmp_path / "stara.dtb"
    legacy_encrypt(plain, old)
    assert dtb.is_dtb(old) and backup.validate(old)["jobs"] >= 1


def test_key_file_is_never_inside_the_backup(data, tmp_path):
    src = make_data(tmp_path / "a")
    (src / "backup.key").write_text("00" * 32)
    z = backup.create(src, tmp_path / "z.zip", encrypt=False)
    assert "backup.key" not in zipfile.ZipFile(z).namelist()


def test_api_restore_asks_for_the_key_and_shows_it(client, tmp_path, monkeypatch):
    c, st = client
    other = make_data(tmp_path / "jina")
    monkeypatch.setenv("VIDDOWN_DATA", str(tmp_path / "jina-instalace"))
    (tmp_path / "jina-instalace").mkdir()
    foreign_key = dtb.format_key(dtb.install_key())
    z = backup.create(other, tmp_path / "cizi.dtb")
    monkeypatch.setenv("VIDDOWN_DATA", str(st.data))
    r = c.post("/api/restore", files={"file": ("cizi.dtb", open(z, "rb"), "application/octet-stream")})
    assert r.status_code == 400 and r.json()["detail"].startswith("KEY_NEEDED")
    r = c.post("/api/restore", files={"file": ("cizi.dtb", open(z, "rb"), "application/octet-stream")}, data={"key": foreign_key})
    assert r.status_code == 200 and r.json()["manifest"]
    k = c.get("/api/backup/key").json()["key"]
    assert dtb.parse_key(k) == dtb.install_key(st.data)
