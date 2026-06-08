import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from invoiceflow import crypto, extractor, ingest, reader, store, webapp, worker, models
from invoiceflow.config import get_settings
from invoiceflow.db import SessionLocal, init_db
from invoiceflow.models import DONE, Job
from invoiceflow.schema import InvoiceFields, Vendor


@pytest.fixture
def client(tmp_path, monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    s = get_settings(str(tmp_path))
    init_db(s)
    return TestClient(webapp.create_app(s))


def test_reader_handles_txt(tmp_path):
    s = get_settings(str(tmp_path))
    r = reader.read_document(b"INVOICE INV-TXT total 5.00", "pasted.txt", s)
    assert r.full_text == "INVOICE INV-TXT total 5.00"
    assert r.used_ocr is False
    assert r.pages[0].words == []


def test_submit_text_creates_job(client):
    r = client.post("/submit", data={"text": "INVOICE INV-PASTE total 7.00"},
                    follow_redirects=False)
    assert r.status_code == 303
    job = store.find_job_by_hash(ingest._sha256(b"INVOICE INV-PASTE total 7.00"))
    assert job is not None and job.source == "upload"
    assert job.source_ref == "pasted.txt"


def test_submit_file_creates_job(client):
    r = client.post("/submit",
                    files={"file": ("scan.pdf", b"%PDF-1.4 m", "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert store.find_job_by_hash(ingest._sha256(b"%PDF-1.4 m")) is not None


def test_submit_text_and_file_is_one_combined_job(client):
    r = client.post("/submit", data={"text": "email body weight 21000kg"},
                    files={"file": ("a.pdf", b"%PDF-1.4 both", "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303
    # ONE job: the attachment is the document; the email text is stored as context
    assert store.find_job_by_hash(ingest._sha256(b"email body weight 21000kg")) is None
    job = store.find_job_by_hash(ingest._sha256(b"%PDF-1.4 both"))
    assert job is not None
    assert crypto.decrypt_str(job.enc_context) == "email body weight 21000kg"


def test_worker_merges_email_context(client, tmp_path, monkeypatch):
    settings = get_settings(str(tmp_path))
    # ingest a combined item: text body + a (fake) pdf attachment
    ingest.UploadSource(settings).ingest_bytes(
        b"%PDF-1.4 doc", "scan.pdf", extra_text="Container MSKU1234567")
    job = store.find_job_by_hash(ingest._sha256(b"%PDF-1.4 doc"))

    monkeypatch.setattr(reader, "read_document",
                        lambda data, name, s: reader.ReaderResult([], "weight 21000kg", False))
    seen = {}
    def capture(text, s):
        seen["text"] = text
        return InvoiceFields(invoice_number="X", invoice_date="2026-01-01", total=1.0)
    monkeypatch.setattr(extractor, "extract_fields", capture)

    worker.process_job(job.id, settings)
    # both the email body and the attachment text reach the extractor
    assert "Container MSKU1234567" in seen["text"]
    assert "weight 21000kg" in seen["text"]


def test_submit_empty_is_noop(client):
    r = client.post("/submit", data={"text": "   "}, follow_redirects=False)
    assert r.status_code == 303
    assert store.list_invoice_summaries() == []


def test_pasted_text_flows_through_worker(client, tmp_path, monkeypatch):
    # end-to-end: paste text -> work -> invoice stored (extractor mocked, no Ollama)
    settings = get_settings(str(tmp_path))
    client.post("/submit", data={"text": "INVOICE INV-E2E total 9.00"})
    job = store.find_job_by_hash(ingest._sha256(b"INVOICE INV-E2E total 9.00"))
    monkeypatch.setattr(extractor, "extract_fields",
                        lambda text, s: InvoiceFields(invoice_number="INV-E2E",
                                                      invoice_date="2026-01-01", total=9.0,
                                                      vendor=Vendor(name="Acme")))
    worker.process_job(job.id, settings)
    with SessionLocal() as s:
        assert s.get(Job, job.id).status == DONE
    rows = store.list_invoice_summaries(status=models.NEEDS_REVIEW)
    assert any(r["invoice_number"] == "INV-E2E" for r in rows)
