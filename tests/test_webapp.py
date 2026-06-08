import os
import pytest
from starlette.testclient import TestClient

from invoiceflow import crypto, ingest, store, webapp
from invoiceflow.config import get_settings
from invoiceflow.db import init_db
from invoiceflow.schema import InvoiceFields, Vendor


@pytest.fixture
def client(tmp_path, monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    s = get_settings(str(tmp_path))
    init_db(s)
    return TestClient(webapp.create_app(s))


def test_list_page_shows_invoices(client):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    store.save_invoice(jid, InvoiceFields(invoice_number="INV-LIST",
                                          vendor=Vendor(name="Acme")), {}, "low")
    r = client.get("/")
    assert r.status_code == 200
    assert "INV-LIST" in r.text


def test_detail_shows_fields_and_reasons(client):
    jid = store.create_job("upload", "a.pdf", "h", "/tmp/none")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="INV-DET", total=1.0),
                             {"total": {"confidence": "low", "reasons": ["arithmetic"]}}, "low")
    r = client.get(f"/invoice/{iid}")
    assert r.status_code == 200
    assert "INV-DET" in r.text
    assert "arithmetic" in r.text


def test_save_edits_persists(client):
    jid = store.create_job("upload", "a.pdf", "h3", "/tmp/none")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="OLD", total=1.0), {}, "low")
    r = client.post(f"/invoice/{iid}",
                    data={"invoice_number": "NEW", "total": "9.99", "vendor_name": "Acme"},
                    follow_redirects=False)
    assert r.status_code == 303
    got = store.get_invoice(iid)
    assert got.fields.invoice_number == "NEW"
    assert got.fields.total == 9.99
    assert got.fields.vendor.name == "Acme"


def test_approve_route(client):
    jid = store.create_job("upload", "a.pdf", "h4", "/tmp/none")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="A"), {}, "low")
    r = client.post(f"/invoice/{iid}/approve", follow_redirects=False)
    assert r.status_code == 303
    assert store.get_invoice(iid).status == "verified"


def test_upload_route_creates_job(client):
    r = client.post("/upload", files={"file": ("u.pdf", b"%PDF-1.4 up", "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert store.find_job_by_hash(ingest._sha256(b"%PDF-1.4 up")) is not None
