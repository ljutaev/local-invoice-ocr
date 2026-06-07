import json

from invoiceflow import extractor
from invoiceflow.config import get_settings


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self): pass
    def json(self): return self._payload


def test_extract_parses_model_json(monkeypatch, tmp_path):
    s = get_settings(str(tmp_path))
    content = json.dumps({"invoice_number": "INV-9", "total": 50.0,
                          "vendor": {"name": "Acme"}})
    monkeypatch.setattr(extractor.httpx, "post",
                        lambda *a, **k: _FakeResp({"message": {"content": content}}))
    fields = extractor.extract_fields("INVOICE INV-9 total 50.00", s)
    assert fields.invoice_number == "INV-9"
    assert fields.total == 50.0
    assert fields.vendor.name == "Acme"


def test_extract_raises_on_bad_json(monkeypatch, tmp_path):
    s = get_settings(str(tmp_path))
    monkeypatch.setattr(extractor.httpx, "post",
                        lambda *a, **k: _FakeResp({"message": {"content": "not json"}}))
    try:
        extractor.extract_fields("x", s)
        assert False, "expected ExtractionError"
    except extractor.ExtractionError:
        pass
