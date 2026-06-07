from invoiceflow import store, models
from invoiceflow.schema import InvoiceFields, Vendor


def test_create_and_find_job(db):
    jid = store.create_job("folder", "/x/a.pdf", "hash123", "/enc/a.bin")
    assert isinstance(jid, int)
    assert store.find_job_by_hash("hash123").id == jid
    assert store.find_job_by_hash("nope") is None


def test_save_and_get_invoice_roundtrip(db):
    jid = store.create_job("folder", "/x/a.pdf", "h", "/enc/a.bin")
    fields = InvoiceFields(invoice_number="INV-1", total=120.0,
                           vendor=Vendor(name="Acme"))
    flags = {"total": {"confidence": "high", "reasons": []}}
    iid = store.save_invoice(jid, fields, flags, "high")
    got = store.get_invoice(iid)
    assert got.fields.invoice_number == "INV-1"
    assert got.fields.vendor.name == "Acme"
    assert got.flags["total"]["confidence"] == "high"
    assert got.status == models.NEEDS_REVIEW


def test_list_invoices_by_status(db):
    jid = store.create_job("folder", "/x/a.pdf", "h", "/enc/a.bin")
    store.save_invoice(jid, InvoiceFields(), {}, "low")
    rows = store.list_invoices(status=models.NEEDS_REVIEW)
    assert len(rows) == 1
