from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# Job statuses
PENDING, PROCESSING, DONE, FAILED = "pending", "processing", "done", "failed"
# Invoice statuses
NEEDS_REVIEW, VERIFIED = "needs_review", "verified"


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_ref: Mapped[str] = mapped_column(String(512))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    enc_file_path: Mapped[str] = mapped_column(String(512))
    enc_context: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # email body text
    status: Mapped[str] = mapped_column(String(16), default=PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=NEEDS_REVIEW, index=True)
    enc_fields: Mapped[bytes] = mapped_column(LargeBinary)        # encrypted JSON
    enc_layout: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # encrypted page/word boxes
    field_flags: Mapped[dict] = mapped_column(JSON, default=dict)  # NOT sensitive
    confidence_summary: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enc_old: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enc_new: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
