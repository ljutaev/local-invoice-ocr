from dataclasses import dataclass

from invoiceflow import crypto
from invoiceflow.db import SessionLocal
from invoiceflow.models import Invoice, Job, NEEDS_REVIEW
from invoiceflow.schema import InvoiceFields


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
