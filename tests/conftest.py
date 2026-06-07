import os
import pytest

from invoiceflow.config import get_settings
from invoiceflow.db import init_db
from invoiceflow import crypto


@pytest.fixture
def settings(tmp_path):
    return get_settings(str(tmp_path))


@pytest.fixture
def db(settings, monkeypatch):
    # deterministic key, no Keychain access in tests
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    init_db(settings)
    return settings
