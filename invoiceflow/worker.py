from datetime import datetime, timezone
from pathlib import Path

from invoiceflow import crypto, extractor, reader, store, validator
from invoiceflow.config import Settings
from invoiceflow.db import SessionLocal
from invoiceflow.models import DONE, FAILED, Job


def process_job(job_id: int, settings: Settings, worker_id: str = "w1") -> None:
    with SessionLocal() as s:
        job = s.get(Job, job_id)
        enc_path, source_ref = job.enc_file_path, job.source_ref
        job.attempts += 1
        s.commit()
    try:
        data = crypto.decrypt(Path(enc_path).read_bytes())
        rr = reader.read_document(data, source_ref, settings)
        fields = extractor.extract_fields(rr.full_text, settings)
        flags, summary = validator.validate(fields, rr.full_text)
        store.save_invoice(job_id, fields, flags, summary)
        _finish(job_id, DONE, None)
    except Exception as e:  # noqa: BLE001 — record and surface in UI
        _finish(job_id, FAILED, str(e))


def _finish(job_id: int, status: str, error: str | None) -> None:
    with SessionLocal() as s:
        job = s.get(Job, job_id)
        job.status = status
        job.error = error
        job.finished_at = datetime.now(timezone.utc)
        s.commit()
