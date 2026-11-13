"""Šifrovaný formát zálohy `.dtb` (AES-256-GCM po blocích).

Klíč je **zabudovaný v aplikaci** (záměr): zálohu otevře jen VidDown a na jakémkoli stroji, bez zadávání hesla.
Je to ochrana před náhodným nahlédnutím do souboru (cloud, USB, e-mail), ne před někým, kdo má kopii aplikace –
klíč lze z jejího kódu vyčíst. Proto se kód ani obraz nesmí zveřejnit.

Formát: MAGIC (6 B) | sůl (16 B) | předpona nonce (4 B) | bloky [délka šifrotextu (4 B) | šifrotext+tag].
Klíč bloků = HKDF-SHA256(hlavní klíč, sůl). Do ověřované hlavičky každého bloku patří pořadí a příznak
posledního bloku, takže jde poznat změna, přeházení i zkrácení souboru.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

MAGIC = b"VDDTB\x01"
CHUNK = 1 << 20
EXT = ".dtb"
_MASTER = bytes.fromhex("a2a4dff501628eb3f1c3611b2d391ced9ab56bd51e79ba49500815332117ebe0")


class DtbError(Exception):
    pass


def _key(salt: bytes) -> bytes:
    prk = hmac.new(salt, _MASTER, hashlib.sha256).digest()                  # HKDF extract
    return hmac.new(prk, b"VidDown backup v1\x01", hashlib.sha256).digest()  # HKDF expand (jeden blok = 32 B)


def is_dtb(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def encrypt_file(src: Path, dst: Path) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, prefix = os.urandom(16), os.urandom(4)
    header = MAGIC + salt + prefix
    aes = AESGCM(_key(salt))
    with open(src, "rb") as f, open(dst, "wb") as out:
        out.write(header)
        buf, idx = f.read(CHUNK), 0
        while True:
            nxt = f.read(CHUNK)
            last = not nxt
            ct = aes.encrypt(prefix + idx.to_bytes(8, "big"), buf, header + idx.to_bytes(8, "big") + (b"\x01" if last else b"\x00"))
            out.write(len(ct).to_bytes(4, "big") + ct)
            if last:
                return
            buf, idx = nxt, idx + 1


def decrypt_file(src: Path, dst: Path) -> None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(src, "rb") as f:
        header = f.read(len(MAGIC) + 20)
        if len(header) != len(MAGIC) + 20 or header[:len(MAGIC)] != MAGIC:
            raise DtbError("soubor není záloha VidDown (.dtb)")
        salt, prefix = header[len(MAGIC):len(MAGIC) + 16], header[len(MAGIC) + 16:]
        aes = AESGCM(_key(salt))

        def read_chunk():
            ln = f.read(4)
            if not ln:
                return None
            if len(ln) != 4:
                raise DtbError("záloha je poškozená (zkrácený soubor)")
            n = int.from_bytes(ln, "big")
            if n < 16 or n > CHUNK + 16:
                raise DtbError("záloha je poškozená")
            ct = f.read(n)
            if len(ct) != n:
                raise DtbError("záloha je poškozená (zkrácený soubor)")
            return ct

        cur, idx = read_chunk(), 0
        if cur is None:
            raise DtbError("záloha je prázdná")
        try:
            with open(dst, "wb") as out:
                while cur is not None:
                    nxt = read_chunk()
                    last = nxt is None
                    out.write(aes.decrypt(prefix + idx.to_bytes(8, "big"), cur,
                                          header + idx.to_bytes(8, "big") + (b"\x01" if last else b"\x00")))
                    cur, idx = nxt, idx + 1
        except InvalidTag as e:
            Path(dst).unlink(missing_ok=True)
            raise DtbError("záloha je poškozená, byla změněna nebo je z nekompatibilní verze šifrování") from e
        except DtbError:
            Path(dst).unlink(missing_ok=True)       # zkrácený soubor: nenechat napůl dešifrovaný výstup
            raise
