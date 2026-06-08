import csv
import json

from invoiceflow import exporter, store
from invoiceflow.schema import InvoiceFields, LineItem, Vendor


def _verified(invoice_number):
    jid = store.create_job("folder", "a.pdf", invoice_number, "/e")
    iid = store.save_invoice(jid, InvoiceFields(
        invoice_number=invoice_number, total=10.0, vendor=Vendor(name="Acme"),
        line_items=[LineItem(description="X", amount=10.0)]), {}, "high")
    store.approve_invoice(iid, "me")
    return iid


def test_export_csv_and_marks_exported(db, settings, tmp_path):
    _verified("INV-1")
    _verified("INV-2")
    out = tmp_path / "out.csv"
    n = exporter.export_verified(out, fmt="csv")
    assert n == 2
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert {r["invoice_number"] for r in rows} == {"INV-1", "INV-2"}
    assert json.loads(rows[0]["line_items"])[0]["amount"] == 10.0
    # already exported → second run finds nothing
    assert exporter.export_verified(tmp_path / "out2.csv", fmt="csv") == 0


def test_export_json(db, settings, tmp_path):
    _verified("INV-9")
    out = tmp_path / "out.json"
    assert exporter.export_verified(out, fmt="json") == 1
    data = json.loads(out.read_text())
    assert data[0]["invoice_number"] == "INV-9"


def test_export_skips_unverified(db, settings, tmp_path):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    store.save_invoice(jid, InvoiceFields(invoice_number="DRAFT"), {}, "low")  # needs_review
    assert exporter.export_verified(tmp_path / "o.csv", fmt="csv") == 0
