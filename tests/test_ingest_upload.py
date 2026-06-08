from pathlib import Path

from invoiceflow import ingest, store, crypto


def test_upload_ingests_bytes(db, settings):
    src = ingest.UploadSource(settings)
    jid = src.ingest_bytes(b"%PDF-1.4 up", "up.pdf")
    assert jid is not None
    job = store.find_job_by_hash(ingest._sha256(b"%PDF-1.4 up"))
    assert job.source == "upload"
    assert crypto.decrypt(Path(job.enc_file_path).read_bytes()) == b"%PDF-1.4 up"


def test_upload_dedup(db, settings):
    src = ingest.UploadSource(settings)
    assert src.ingest_bytes(b"dup", "a.pdf") is not None
    assert src.ingest_bytes(b"dup", "b.pdf") is None
