import os
import pytest
from starlette.testclient import TestClient

from invoiceflow import crypto, store, webapp
from invoiceflow.config import get_settings
from invoiceflow.db import init_db
from invoiceflow.schema import InvoiceFields, LineItem


@pytest.fixture
def client(tmp_path, monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    s = get_settings(str(tmp_path))
    init_db(s)
    return TestClient(webapp.create_app(s))


def test_edit_line_items_persists(client):
    jid = store.create_job("upload", "a.pdf", "h", "/tmp/none")
    iid = store.save_invoice(jid, InvoiceFields(
        invoice_number="INV-1",
        line_items=[LineItem(description="Old", qty=1.0, unit_price=5.0, amount=5.0)]),
        {}, "low")
    r = client.post(f"/invoice/{iid}", data={
        "invoice_number": "INV-1",
        "li_0_description": "Widgets", "li_0_qty": "3",
        "li_0_unit_price": "4.00", "li_0_amount": "12.00",
    }, follow_redirects=False)
    assert r.status_code == 303
    li = store.get_invoice(iid).fields.line_items
    assert len(li) == 1
    assert li[0].description == "Widgets"
    assert li[0].qty == 3.0
    assert li[0].amount == 12.0
