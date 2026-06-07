from pathlib import Path

from invoiceflow import worker, store, ingest, reader, extractor, validator, models
from invoiceflow.db import SessionLocal
from invoiceflow.models import Job, DONE
from invoiceflow.schema import InvoiceFields, Vendor


def test_process_job_full_path(db, settings, monkeypatch):
    f = Path(settings.inbox_dir) / "a.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    jid = ingest.FolderSource(settings).ingest_file(f)

    monkeypatch.setattr(reader, "read_document",
                        lambda data, name, s: reader.ReaderResult([], "INV-1 total 10.00", False))
    monkeypatch.setattr(extractor, "extract_fields",
                        lambda text, s: InvoiceFields(invoice_number="INV-1", total=10.0,
                                                      invoice_date="2026-01-01",
                                                      vendor=Vendor(name="Acme")))

    worker.process_job(jid, settings, worker_id="w1")

    with SessionLocal() as s:
        assert s.get(Job, jid).status == DONE
    rows = store.list_invoices(status=models.NEEDS_REVIEW)
    assert len(rows) == 1


def test_process_job_marks_failed_on_extractor_error(db, settings, monkeypatch):
    f = Path(settings.inbox_dir) / "b.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    jid = ingest.FolderSource(settings).ingest_file(f)
    monkeypatch.setattr(reader, "read_document",
                        lambda data, name, s: reader.ReaderResult([], "x", False))
    def boom(text, s): raise extractor.ExtractionError("nope")
    monkeypatch.setattr(extractor, "extract_fields", boom)

    worker.process_job(jid, settings, worker_id="w1")
    with SessionLocal() as s:
        assert s.get(Job, jid).status == models.FAILED
        assert "nope" in s.get(Job, jid).error
