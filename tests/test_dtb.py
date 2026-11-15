"""Šifrovaný formát zálohy .dtb (v2: klíč záloh instalace; v1: starší zálohy se zabudovaným klíčem jen ke čtení)."""
import os
import re
import sqlite3

import pytest

from tests.test_backup import make_data, names
from viddown import backup, dtb
from viddown.db import DB


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch):
    monkeypatch.setattr(dtb, "CHUNK", 1000)       # ať se vícebloková cesta zkouší i na malých souborech


def roundtrip(tmp_path, payload: bytes):
    src, enc, out = tmp_path / "a", tmp_path / "a.dtb", tmp_path / "b"
    src.write_bytes(payload)
    dtb.encrypt_file(src, enc)
    dtb.decrypt_file(enc, out)
    return enc, out.read_bytes()


@pytest.mark.parametrize("size", [0, 1, 999, 1000, 1001, 2000, 5321])
def test_roundtrip_various_sizes(tmp_path, size):
    payload = os.urandom(size)
    enc, back = roundtrip(tmp_path, payload)
    assert back == payload and dtb.is_dtb(enc)


def test_no_plaintext_and_random_each_time(tmp_path):
    payload = b"tajny-token-123:ABC" * 200
    enc1, _ = roundtrip(tmp_path, payload)
    data1 = enc1.read_bytes()
    assert b"tajny-token" not in data1
    (tmp_path / "x").mkdir()
    enc2, _ = roundtrip(tmp_path / "x", payload)
    assert data1 != enc2.read_bytes()                 # náhodná sůl a nonce


def test_tampering_is_detected(tmp_path):
    enc, _ = roundtrip(tmp_path, os.urandom(3500))
    raw = enc.read_bytes()
    out = tmp_path / "o"

    def check(data, match):
        bad = tmp_path / "bad.dtb"
        bad.write_bytes(data)
        with pytest.raises(dtb.DtbError, match=match):
            dtb.decrypt_file(bad, out)
        assert not out.exists()                                    # po chybě nezůstane napůl dešifrovaný soubor

    flipped = bytearray(raw)
    flipped[len(raw) // 2] ^= 0xFF
    check(bytes(flipped), "poškozená|změněna")
    check(raw[:-5], "poškozená")                                   # zkrácený poslední blok
    hl = len(dtb.MAGIC) + 28                                       # hlavička v2: magic + otisk klíče + sůl + předpona nonce
    first_len = int.from_bytes(raw[hl:hl + 4], "big")
    check(raw[:hl + 4 + first_len], "poškozená|změněna")           # useknuto přesně na hranici bloku
    # přehození dvou bloků
    h, rest = raw[:hl], raw[hl:]
    chunks, i = [], 0
    while i < len(rest):
        n = int.from_bytes(rest[i:i + 4], "big")
        chunks.append(rest[i:i + 4 + n])
        i += 4 + n
    check(h + chunks[1] + chunks[0] + b"".join(chunks[2:]), "poškozená|změněna")
    check(b"neco jineho", "není záloha")
    check(b"", "není záloha")


def test_backup_default_is_encrypted_dtb_and_roundtrips(tmp_path):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / backup.default_name())
    assert re.fullmatch(r"VidDown_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.dtb", z.name)
    raw = z.read_bytes()
    assert raw.startswith(dtb.MAGIC) and not raw.startswith(b"PK") and b"viddown.db" not in raw
    assert backup.validate(z)["jobs"] == 1
    dst = tmp_path / "jiny-stroj"
    dst.mkdir()
    backup.apply(dst, z)                                # žádné heslo, žádný klíč navíc
    assert json_token(dst) == "123:ABC"
    assert len(DB(dst / "viddown.db").query("select * from jobs")) == 1
    assert not list(tmp_path.glob("**/*.enc"))          # po sobě neuklidí dočasné soubory


def json_token(d):
    import json
    return json.loads((d / "secrets.json").read_text())["telegram_token"]


def test_plain_zip_still_works_and_both_are_accepted(tmp_path):
    src = make_data(tmp_path / "a")
    plain = backup.create(src, tmp_path / "p.zip", encrypt=False)
    enc = backup.create(src, tmp_path / "e.dtb")
    assert names(plain) and backup.validate(plain)["jobs"] == backup.validate(enc)["jobs"] == 1


def test_corrupted_dtb_is_rejected_cleanly(tmp_path):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "e.dtb")
    raw = bytearray(z.read_bytes())
    raw[100] ^= 0x55
    z.write_bytes(bytes(raw))
    with pytest.raises(backup.BackupError, match="poškozená|změněna"):
        backup.validate(z)
    dst = make_data(tmp_path / "dst", paths=("/stary",), token="STARY")
    with pytest.raises(backup.BackupError):
        backup.apply(dst, z)
    assert json_token(dst) == "STARY"                   # nic se nezměnilo


def test_staged_dtb_stays_encrypted_at_rest_and_applies_at_start(tmp_path):
    src = make_data(tmp_path / "a")
    z = backup.create(src, tmp_path / "e.dtb")
    dst = make_data(tmp_path / "dst", paths=("/stary",), token="STARY")
    backup.stage(dst, z)
    assert (dst / "restore" / "pending.zip").read_bytes().startswith(dtb.MAGIC)
    res = backup.apply_pending(dst)
    assert res["ok"] and json_token(dst) == "123:ABC"
