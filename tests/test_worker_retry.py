from pathlib import Path
from dataclasses import replace

from invoiceflow import worker, ingest, extractor, reader
from invoiceflow.db import SessionLocal
from invoiceflow.models import Job, PENDING, FAILED


def test_requeues_then_fails(db, settings, monkeypatch):
    s = replace(settings, max_attempts=2)
    f = Path(settings.inbox_dir) / "a.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    jid = ingest.FolderSource(settings).ingest_file(f)

    monkeypatch.setattr(reader, "read_document",
                        lambda data, name, st: reader.ReaderResult([], "x", False))
    def boom(text, st):
        raise extractor.ExtractionError("ollama down")
    monkeypatch.setattr(extractor, "extract_fields", boom)

    worker.process_job(jid, s)             # attempt 1 < 2 → requeue
    with SessionLocal() as sess:
        assert sess.get(Job, jid).status == PENDING

    worker.process_job(jid, s)             # attempt 2 == max → failed
    with SessionLocal() as sess:
        job = sess.get(Job, jid)
        assert job.status == FAILED
        assert "ollama down" in job.error
