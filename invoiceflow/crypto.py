import base64
import os

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_SERVICE = "invoiceflow"
_KEY_NAME = "master-key"
_NONCE = 12


def get_key() -> bytes:
    """32-byte master key from macOS Keychain; created on first use."""
    stored = keyring.get_password(_SERVICE, _KEY_NAME)
    if stored is None:
        key = os.urandom(32)
        keyring.set_password(_SERVICE, _KEY_NAME, base64.b64encode(key).decode())
        return key
    return base64.b64decode(stored)


def encrypt(data: bytes) -> bytes:
    nonce = os.urandom(_NONCE)
    ct = AESGCM(get_key()).encrypt(nonce, data, None)
    return nonce + ct


def decrypt(blob: bytes) -> bytes:
    return AESGCM(get_key()).decrypt(blob[:_NONCE], blob[_NONCE:], None)


def encrypt_str(s: str) -> bytes:
    return encrypt(s.encode("utf-8"))


def decrypt_str(blob: bytes) -> str:
    return decrypt(blob).decode("utf-8")
