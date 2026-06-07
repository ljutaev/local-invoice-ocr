import os
from invoiceflow import crypto


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    blob = crypto.encrypt(b"secret invoice total 1234.56")
    assert blob != b"secret invoice total 1234.56"
    assert crypto.decrypt(blob) == b"secret invoice total 1234.56"


def test_str_helpers(monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    assert crypto.decrypt_str(crypto.encrypt_str("Acme Ltd")) == "Acme Ltd"


def test_unique_nonce(monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    assert crypto.encrypt(b"x") != crypto.encrypt(b"x")  # random nonce
