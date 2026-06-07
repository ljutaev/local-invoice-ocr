from pathlib import Path

from invoiceflow import ingest, store, crypto


def test_ingest_creates_job_and_encrypts(db, settings):
    f = Path(settings.inbox_dir) / "a.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    src = ingest.FolderSource(settings)
    jid = src.ingest_file(f)
    assert jid is not None
    job = store.find_job_by_hash(src.hash_file(f))
    # original is encrypted on disk and decrypts back to the bytes
    enc = Path(job.enc_file_path).read_bytes()
    assert crypto.decrypt(enc) == b"%PDF-1.4 fake"


def test_ingest_dedup_returns_none(db, settings):
    f = Path(settings.inbox_dir) / "a.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    src = ingest.FolderSource(settings)
    assert src.ingest_file(f) is not None
    assert src.ingest_file(f) is None  # same hash → skip
