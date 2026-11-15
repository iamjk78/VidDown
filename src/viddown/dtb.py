"""Šifrovaný formát zálohy `.dtb` (AES-256-GCM po blocích).

**Verze 2 (současná):** klíč je náhodný a patří jedné instalaci – leží v datové složce v souboru `backup.key` (práva 600)
a do zálohy se nikdy nedostane. Na stejné instalaci se záloha obnoví bez zadávání čehokoli; na jiném počítači je potřeba
zadat „klíč záloh“ z původní instalace (GUI ho ukáže v Nastavení › Záloha a obnova). Kód aplikace je veřejný, proto
klíč nesmí být zabudovaný v aplikaci.

**Verze 1 (starší zálohy):** klíč zabudovaný v aplikaci. Takové zálohy jde dál obnovit, nově se už nevytvářejí; protože je
kód veřejný, chrání jen před náhodným nahlédnutím.

Formát v2: MAGIC (6 B) | otisk klíče (8 B) | sůl (16 B) | předpona nonce (4 B) | bloky [délka šifrotextu (4 B) | šifrotext+tag].
Formát v1: MAGIC (6 B) | sůl (16 B) | předpona nonce (4 B) | bloky.
Klíč bloků = HKDF-SHA256(klíč, sůl). Do ověřované hlavičky každého bloku patří pořadí a příznak posledního bloku, takže jde
poznat změna, přeházení i zkrácení souboru.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from pathlib import Path

MAGIC1 = b"VDDTB\x01"
MAGIC2 = b"VDDTB\x02"
MAGIC = MAGIC2
CHUNK = 1 << 20
EXT = ".dtb"
KEY_FILE = "backup.key"
_LEGACY = bytes.fromhex("a2a4dff501628eb3f1c3611b2d391ced9ab56bd51e79ba49500815332117ebe0")      # jen pro čtení záloh v1


class DtbError(Exception):
    pass


class KeyNeeded(DtbError):
    """Záloha je zašifrovaná klíčem jiné instalace: je potřeba zadat klíč záloh z ní."""


def _derive(master: bytes, salt: bytes, info: bytes) -> bytes:
    prk = hmac.new(salt, master, hashlib.sha256).digest()                   # HKDF extract
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()           # HKDF expand (jeden blok = 32 B)


def fingerprint(key: bytes) -> bytes:
    return hashlib.sha256(b"VidDown backup key id" + key).digest()[:8]


# --- klíč instalace ----------------------------------------------------------------------------------------------------
def install_key(data: Path | None = None) -> bytes:
    """Klíč záloh této instalace (vytvoří se při první potřebě)."""
    if data is None:
        from .config import data_dir
        data = data_dir()
    p = Path(data) / KEY_FILE
    try:
        k = bytes.fromhex(p.read_text().strip())
        if len(k) == 32:
            return k
    except (OSError, ValueError):
        pass
    k = os.urandom(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(k.hex())
    os.replace(tmp, p)
    return k


def format_key(key: bytes) -> str:
    """Čitelný tvar klíče pro uživatele: skupiny po čtyřech znacích base32 (bez záměnných znaků nezáleží na velikosti písmen)."""
    s = base64.b32encode(key).decode().rstrip("=")
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def parse_key(text: str) -> bytes:
    s = re.sub(r"[\s-]", "", (text or "").upper())
    if not s:
        raise DtbError("klíč záloh je prázdný")
    try:
        k = base64.b32decode(s + "=" * (-len(s) % 8))
    except (ValueError, base64.binascii.Error) as e:
        raise DtbError("klíč záloh má špatný tvar (opište ho přesně, včetně pomlček nebo bez nich)") from e
    if len(k) != 32:
        raise DtbError("klíč záloh má špatnou délku")
    return k


# --- šifrování ---------------------------------------------------------------------------------------------------------
def is_dtb(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC1)) in (MAGIC1, MAGIC2)
    except OSError:
        return False


def encrypt_file(src: Path, dst: Path, key: bytes | None = None) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = key if key is not None else install_key()
    salt, prefix = os.urandom(16), os.urandom(4)
    header = MAGIC2 + fingerprint(key) + salt + prefix
    aes = AESGCM(_derive(key, salt, b"VidDown backup v2"))
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)        # záloha obsahuje tajemství: jen pro vlastníka
    with open(src, "rb") as f, os.fdopen(fd, "wb") as out:
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


def decrypt_file(src: Path, dst: Path, keys: list[bytes] | tuple = (), data: Path | None = None) -> None:
    """Dešifruje zálohu. Zkouší klíč této instalace a pak klíče v `keys` (zadané uživatelem). Záloha jiné instalace bez
    správného klíče vyhodí `KeyNeeded`."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(src, "rb") as f:
        magic = f.read(len(MAGIC1))
        if magic == MAGIC1:
            rest = f.read(20)
            if len(rest) != 20:
                raise DtbError("záloha je poškozená (zkrácený soubor)")
            header, salt, prefix = magic + rest, rest[:16], rest[16:]
            aes = AESGCM(_derive(_LEGACY, salt, b"VidDown backup v1"))
        elif magic == MAGIC2:
            rest = f.read(28)
            if len(rest) != 28:
                raise DtbError("záloha je poškozená (zkrácený soubor)")
            header, fp, salt, prefix = magic + rest, rest[:8], rest[8:24], rest[24:]
            cands = [install_key(data), *keys]
            key = next((k for k in cands if fingerprint(k) == fp), None)
            if key is None:
                raise KeyNeeded("záloha je zašifrovaná klíčem jiné instalace VidDown: zadejte její klíč záloh "
                                "(původní instalace ho ukazuje v Nastavení › Záloha a obnova)")
            aes = AESGCM(_derive(key, salt, b"VidDown backup v2"))
        else:
            raise DtbError("soubor není záloha VidDown (.dtb)")

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
