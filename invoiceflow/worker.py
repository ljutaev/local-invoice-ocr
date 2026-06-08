import json
from datetime import datetime, timezone
from pathlib import Path

from invoiceflow import crypto, extractor, reader, store, validator
from invoiceflow.config import Settings
from invoiceflow.db import SessionLocal
from invoiceflow.models import DONE, FAILED, PENDING, Job


def process_job(job_id: int, settings: Settings, worker_id: str = "w1") -> None:
    with SessionLocal() as s:
        job = s.get(Job, job_id)
        enc_path, source_ref = job.enc_file_path, job.source_ref
        enc_context = job.enc_context
        job.attempts += 1
        attempts = job.attempts
        s.commit()
    try:
        data = crypto.decrypt(Path(enc_path).read_bytes())
        rr = reader.read_document(data, source_ref, settings)
        # email body text (if any) is merged into the extraction/grounding source
        text = rr.full_text
        if enc_context:
            text = crypto.decrypt_str(enc_context) + "\n\n" + rr.full_text
        fields = extractor.extract_fields(text, settings)
        flags, summary = validator.validate(fields, text)
        layout = {"pages": [{"w": p.width, "h": p.height, "words": p.words}
                            for p in rr.pages]}
        store.save_invoice(job_id, fields, flags, summary, layout_json=json.dumps(layout))
        _finish(job_id, DONE, None)
    except Exception as e:  # noqa: BLE001 — record and surface in UI
        if attempts < settings.max_attempts:
            _requeue(job_id, f"retry after error: {e}")
        else:
            _finish(job_id, FAILED, str(e))


def _finish(job_id: int, status: str, error: str | None) -> None:
    with SessionLocal() as s:
        job = s.get(Job, job_id)
        job.status = status
        job.error = error
        job.finished_at = datetime.now(timezone.utc)
        s.commit()


def _requeue(job_id: int, note: str) -> None:
    with SessionLocal() as s:
        job = s.get(Job, job_id)
        job.status = PENDING
        job.error = note
        job.started_at = None
        job.finished_at = None
        s.commit()
