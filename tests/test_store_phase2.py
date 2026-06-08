import json

from invoiceflow import store, crypto
from invoiceflow.db import SessionLocal
from invoiceflow.models import AuditLog
from invoiceflow.schema import InvoiceFields, Vendor


def test_update_writes_fields_and_audit(db):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="INV-1", total=10.0), {}, "high")
    store.update_invoice_fields(iid, InvoiceFields(invoice_number="INV-1", total=12.5,
                                                   vendor=Vendor(name="Acme")), user="me")
    got = store.get_invoice(iid)
    assert got.fields.total == 12.5
    assert got.fields.vendor.name == "Acme"
    with SessionLocal() as s:
        logs = s.query(AuditLog).filter(AuditLog.invoice_id == iid).all()
        changed = {l.field for l in logs}
        assert "total" in changed and "vendor" in changed
        tot = next(l for l in logs if l.field == "total")
        assert json.loads(crypto.decrypt_str(tot.enc_new)) == 12.5


def test_approve_sets_verified(db):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="INV-1"), {}, "low")
    store.approve_invoice(iid, user="me")
    got = store.get_invoice(iid)
    assert got.status == "verified"
    with SessionLocal() as s:
        from invoiceflow.models import Invoice as I
        assert s.get(I, iid).verified_by == "me"


def test_summaries_decrypt_within_session(db):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    store.save_invoice(jid, InvoiceFields(invoice_number="INV-7", total=5.0,
                                          vendor=Vendor(name="Acme")), {}, "high")
    rows = store.list_invoice_summaries()
    assert rows[0]["invoice_number"] == "INV-7"
    assert rows[0]["vendor"] == "Acme"
    assert rows[0]["total"] == 5.0


def test_get_original_bytes_roundtrip(db, settings, tmp_path):
    enc_path = tmp_path / "x.bin"
    enc_path.write_bytes(crypto.encrypt(b"%PDF-1.4 hello"))
    jid = store.create_job("folder", "x.pdf", "h2", str(enc_path))
    iid = store.save_invoice(jid, InvoiceFields(), {}, "low")
    data, media = store.get_original_bytes(iid)
    assert data == b"%PDF-1.4 hello"
    assert media == "application/pdf"
