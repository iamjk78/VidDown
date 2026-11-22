"""Testovací klíč pro podpis vydání. Odvozuje se z pevného seedu, takže v repozitáři není žádný klíč; nepoužívá se v produkci."""
import base64
import hashlib

from cryptography.hazmat.primitives import serialization as _s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"viddown-test-only-signing-seed").digest())
TEST_PRIV_B64 = base64.b64encode(_key.private_bytes(_s.Encoding.Raw, _s.PrivateFormat.Raw, _s.NoEncryption())).decode()
TEST_PUB_B64 = base64.b64encode(_key.public_key().public_bytes(_s.Encoding.Raw, _s.PublicFormat.Raw)).decode()
