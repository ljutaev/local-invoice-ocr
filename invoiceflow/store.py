import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from invoiceflow import crypto
from invoiceflow.db import SessionLocal
from invoiceflow.models import AuditLog, Invoice, Job, NEEDS_REVIEW, VERIFIED
from invoiceflow.schema import InvoiceFields

_MEDIA = {".pdf": "application/pdf", ".png": "image/png",
          ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


@dataclass
class LoadedInvoice:
    id: int
    job_id: int
    status: str
    fields: InvoiceFields
    flags: dict


def create_job(source: str, source_ref: str, file_hash: str, enc_file_path: str) -> int:
    with SessionLocal() as s:
        job = Job(source=source, source_ref=source_ref,
                  file_hash=file_hash, enc_file_path=enc_file_path)
        s.add(job)
        s.commit()
        return job.id


def find_job_by_hash(file_hash: str) -> Job | None:
    with SessionLocal() as s:
        return s.query(Job).filter(Job.file_hash == file_hash).first()


def save_invoice(job_id: int, fields: InvoiceFields, flags: dict, summary: str) -> int:
    enc = crypto.encrypt_str(fields.model_dump_json())
    with SessionLocal() as s:
        inv = Invoice(job_id=job_id, status=NEEDS_REVIEW, enc_fields=enc,
                      field_flags=flags, confidence_summary=summary)
        s.add(inv)
        s.commit()
        return inv.id


def get_invoice(invoice_id: int) -> LoadedInvoice:
    with SessionLocal() as s:
        inv = s.get(Invoice, invoice_id)
        fields = InvoiceFields.model_validate_json(crypto.decrypt_str(inv.enc_fields))
        return LoadedInvoice(inv.id, inv.job_id, inv.status, fields, inv.field_flags)


def list_invoices(status: str | None = None) -> list[Invoice]:
    with SessionLocal() as s:
        q = s.query(Invoice)
        if status:
            q = q.filter(Invoice.status == status)
        return q.order_by(Invoice.created_at.desc()).all()


def list_invoice_summaries(status: str | None = None) -> list[dict]:
    with SessionLocal() as s:
        q = s.query(Invoice)
        if status:
            q = q.filter(Invoice.status == status)
        rows = q.order_by(Invoice.created_at.desc()).all()
        out = []
        for inv in rows:
            f = InvoiceFields.model_validate_json(crypto.decrypt_str(inv.enc_fields))
            out.append({
                "id": inv.id, "status": inv.status, "summary": inv.confidence_summary,
                "invoice_number": f.invoice_number, "vendor": f.vendor.name,
                "total": f.total,
            })
        return out


def update_invoice_fields(invoice_id: int, new_fields: InvoiceFields, user: str) -> None:
    with SessionLocal() as s:
        inv = s.get(Invoice, invoice_id)
        old = InvoiceFields.model_validate_json(crypto.decrypt_str(inv.enc_fields))
        old_d, new_d = old.model_dump(), new_fields.model_dump()
        for k in new_d:
            if old_d.get(k) != new_d.get(k):
                s.add(AuditLog(
                    invoice_id=invoice_id, action="edit", field=k,
                    enc_old=crypto.encrypt_str(json.dumps(old_d.get(k), default=str)),
                    enc_new=crypto.encrypt_str(json.dumps(new_d.get(k), default=str)),
                    user=user,
                ))
        inv.enc_fields = crypto.encrypt_str(new_fields.model_dump_json())
        s.commit()


def approve_invoice(invoice_id: int, user: str) -> None:
    with SessionLocal() as s:
        inv = s.get(Invoice, invoice_id)
        inv.status = VERIFIED
        inv.verified_at = datetime.now(timezone.utc)
        inv.verified_by = user
        s.add(AuditLog(invoice_id=invoice_id, action="approve", user=user))
        s.commit()


def get_original_bytes(invoice_id: int) -> tuple[bytes, str]:
    with SessionLocal() as s:
        inv = s.get(Invoice, invoice_id)
        job = s.get(Job, inv.job_id)
        enc = Path(job.enc_file_path).read_bytes()
        data = crypto.decrypt(enc)
        ext = Path(job.source_ref).suffix.lower()
    return data, _MEDIA.get(ext, "application/octet-stream")


def list_verified_unexported() -> list[dict]:
    with SessionLocal() as s:
        rows = s.query(Invoice).filter(
            Invoice.status == VERIFIED, Invoice.exported_at.is_(None)
        ).order_by(Invoice.verified_at).all()
        out = []
        for inv in rows:
            f = InvoiceFields.model_validate_json(crypto.decrypt_str(inv.enc_fields))
            out.append({"id": inv.id, "fields": f})
        return out


def mark_exported(ids: list[int]) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as s:
        for iid in ids:
            inv = s.get(Invoice, iid)
            if inv:
                inv.exported_at = now
        s.commit()
