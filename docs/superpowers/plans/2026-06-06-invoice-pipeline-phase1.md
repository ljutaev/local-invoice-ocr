# Invoice Pipeline — Phase 1 (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully local, end-to-end invoice ingestion pipeline that watches a folder, reads PDFs/scans, extracts structured fields with a local LLM, scores per-field confidence, and stores everything encrypted in SQLite — verifiable via a CLI.

**Architecture:** A folder source hashes + encrypts each incoming file and enqueues a job. A worker claims jobs from a SQLite-backed queue, runs a two-stage reader (PyMuPDF text or Tesseract OCR), extracts a strict JSON schema via Ollama, validates with rule-based confidence, and persists encrypted results. No data leaves the machine.

**Tech Stack:** Python 3.11, PyMuPDF (fitz), pytesseract + Pillow, httpx (Ollama API), SQLAlchemy 2 + SQLite (WAL), `cryptography` (AES-256-GCM), `keyring` (macOS Keychain), pydantic, pytest.

---

## Spec → Plan mapping
- §3.1 ingest → Task 6 · §3.2 queue → Task 5 · §3.3 reader → Task 7 · §3.4 extractor → Task 8
- §3.5 validator → Task 9 · §3.6 store/crypto/db → Tasks 2,3,4 · §3.9 worker → Task 10 · CLI → Task 11
- Review UI (§3.7), exporter (§3.8), email source — **Phase 2/3, separate plans.**

## File structure (created in this plan)
```
pyproject.toml                  packaging + deps + pytest config
invoiceflow/
  __init__.py
  config.py        Settings dataclass + get_settings() (env overrides)
  crypto.py        AES-256-GCM encrypt/decrypt; key from Keychain
  db.py            engine, SessionLocal, init_db(), WAL pragma
  models.py        ORM: Job, Invoice, AuditLog + status constants
  schema.py        pydantic LineItem/InvoiceFields + INVOICE_JSON_SCHEMA
  store.py         create_job, find_job_by_hash, save_invoice, get_invoice, list_invoices
  queue.py         claim_next_job() — atomic SQLite claim
  ingest.py        FolderSource.ingest_file() — hash/dedup/encrypt/enqueue
  reader.py        read_document() — PDF text vs OCR; Page/ReaderResult
  extractor.py     extract_fields() — Ollama structured JSON
  validator.py     validate() — arithmetic/grounding/required rules
  worker.py        process_job() — orchestration
  cli.py           watch / work / list commands
tests/
  conftest.py      fixtures: tmp settings, in-memory-ish sqlite, sample PDF
  test_crypto.py test_store.py test_queue.py test_ingest.py
  test_reader.py test_extractor.py test_validator.py test_worker.py
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `invoiceflow/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "invoiceflow"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pymupdf>=1.24",
    "pytesseract>=0.3.10",
    "pillow>=10.0",
    "httpx>=0.27",
    "sqlalchemy>=2.0",
    "cryptography>=42.0",
    "keyring>=25.0",
    "pydantic>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
invoiceflow = "invoiceflow.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Create empty package markers**

`invoiceflow/__init__.py` and `tests/__init__.py` — both empty files.

- [ ] **Step 3: Install (editable) + Tesseract**

Run:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
brew install tesseract
```
Expected: install succeeds; `tesseract --version` prints a version.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml invoiceflow/__init__.py tests/__init__.py
git commit -m "chore: scaffold invoiceflow package"
```

---

### Task 2: Config

**Files:**
- Create: `invoiceflow/config.py`

- [ ] **Step 1: Write `config.py`**

```python
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    inbox_dir: Path
    store_dir: Path          # encrypted originals
    db_path: Path
    ollama_url: str
    model: str
    ocr_lang: str
    text_threshold: int      # min chars/page to treat PDF as digital
    max_attempts: int


def get_settings(base: str | None = None) -> Settings:
    base_dir = Path(base or os.environ.get("INVOICEFLOW_HOME", "~/.invoiceflow")).expanduser()
    return Settings(
        base_dir=base_dir,
        inbox_dir=base_dir / "inbox",
        store_dir=base_dir / "store",
        db_path=base_dir / "invoiceflow.db",
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        model=os.environ.get("INVOICEFLOW_MODEL", "qwen2.5:14b"),
        ocr_lang=os.environ.get("INVOICEFLOW_OCR_LANG", "eng"),
        text_threshold=int(os.environ.get("INVOICEFLOW_TEXT_THRESHOLD", "100")),
        max_attempts=int(os.environ.get("INVOICEFLOW_MAX_ATTEMPTS", "3")),
    )


def ensure_dirs(s: Settings) -> None:
    for d in (s.base_dir, s.inbox_dir, s.store_dir):
        d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Commit**

```bash
git add invoiceflow/config.py
git commit -m "feat: settings/config"
```

---

### Task 3: Encryption (AES-256-GCM + Keychain)

**Files:**
- Create: `invoiceflow/crypto.py`, `tests/test_crypto.py`

- [ ] **Step 1: Write the failing test** (`tests/test_crypto.py`)

```python
import os
from invoiceflow import crypto


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    blob = crypto.encrypt(b"secret invoice total 1234.56")
    assert blob != b"secret invoice total 1234.56"
    assert crypto.decrypt(blob) == b"secret invoice total 1234.56"


def test_str_helpers(monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    assert crypto.decrypt_str(crypto.encrypt_str("Acme Ltd")) == "Acme Ltd"


def test_unique_nonce(monkeypatch):
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    assert crypto.encrypt(b"x") != crypto.encrypt(b"x")  # random nonce
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_crypto.py -v`
Expected: FAIL (module `crypto` has no attribute `encrypt`).

- [ ] **Step 3: Write `crypto.py`**

```python
import base64
import os

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_SERVICE = "invoiceflow"
_KEY_NAME = "master-key"
_NONCE = 12


def get_key() -> bytes:
    """32-byte master key from macOS Keychain; created on first use."""
    stored = keyring.get_password(_SERVICE, _KEY_NAME)
    if stored is None:
        key = os.urandom(32)
        keyring.set_password(_SERVICE, _KEY_NAME, base64.b64encode(key).decode())
        return key
    return base64.b64decode(stored)


def encrypt(data: bytes) -> bytes:
    nonce = os.urandom(_NONCE)
    ct = AESGCM(get_key()).encrypt(nonce, data, None)
    return nonce + ct


def decrypt(blob: bytes) -> bytes:
    return AESGCM(get_key()).decrypt(blob[:_NONCE], blob[_NONCE:], None)


def encrypt_str(s: str) -> bytes:
    return encrypt(s.encode("utf-8"))


def decrypt_str(blob: bytes) -> str:
    return decrypt(blob).decode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_crypto.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add invoiceflow/crypto.py tests/test_crypto.py
git commit -m "feat: AES-256-GCM crypto with Keychain key"
```

---

### Task 4: Database + models

**Files:**
- Create: `invoiceflow/db.py`, `invoiceflow/models.py`

- [ ] **Step 1: Write `models.py`**

```python
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
    status: Mapped[str] = mapped_column(String(16), default=PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
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
    field_flags: Mapped[dict] = mapped_column(JSON, default=dict)  # NOT sensitive
    confidence_summary: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


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
```

- [ ] **Step 2: Write `db.py`** (WAL pragma + init)

```python
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from invoiceflow.config import Settings, ensure_dirs
from invoiceflow.models import Base

_engine = None
SessionLocal = sessionmaker()


def init_db(settings: Settings):
    global _engine
    ensure_dirs(settings)
    _engine = create_engine(f"sqlite:///{settings.db_path}", future=True)

    @event.listens_for(_engine, "connect")
    def _set_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(_engine)
    SessionLocal.configure(bind=_engine, future=True)
    return _engine


def get_engine():
    if _engine is None:
        raise RuntimeError("init_db() not called")
    return _engine
```

- [ ] **Step 3: Smoke-check**

Run:
```bash
python -c "from invoiceflow.config import get_settings; from invoiceflow.db import init_db; init_db(get_settings('/tmp/iftest')); print('ok')"
```
Expected: prints `ok`; `/tmp/iftest/invoiceflow.db` exists.

- [ ] **Step 4: Commit**

```bash
git add invoiceflow/db.py invoiceflow/models.py
git commit -m "feat: sqlite db + ORM models"
```

---

### Task 5: Invoice schema (pydantic + JSON schema)

**Files:**
- Create: `invoiceflow/schema.py`

- [ ] **Step 1: Write `schema.py`**

```python
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = ""
    qty: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class Vendor(BaseModel):
    name: str = ""
    address: str = ""
    tax_id: str = ""


class InvoiceFields(BaseModel):
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    vendor: Vendor = Field(default_factory=Vendor)
    buyer_name: str = ""
    currency: str = ""
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    po_number: str = ""
    payment_terms: str = ""


# JSON schema handed to Ollama `format` to force valid structured output.
INVOICE_JSON_SCHEMA = InvoiceFields.model_json_schema()
```

- [ ] **Step 2: Smoke-check**

Run: `python -c "from invoiceflow.schema import INVOICE_JSON_SCHEMA; print(type(INVOICE_JSON_SCHEMA))"`
Expected: `<class 'dict'>`.

- [ ] **Step 3: Commit**

```bash
git add invoiceflow/schema.py
git commit -m "feat: invoice pydantic schema"
```

---

### Task 6: Store (encrypted persistence)

**Files:**
- Create: `invoiceflow/store.py`, `tests/conftest.py`, `tests/test_store.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import os
import pytest

from invoiceflow.config import get_settings
from invoiceflow.db import init_db
from invoiceflow import crypto


@pytest.fixture
def settings(tmp_path):
    return get_settings(str(tmp_path))


@pytest.fixture
def db(settings, monkeypatch):
    # deterministic key, no Keychain access in tests
    key = os.urandom(32)
    monkeypatch.setattr(crypto, "get_key", lambda: key)
    init_db(settings)
    return settings
```

- [ ] **Step 2: Write the failing test** (`tests/test_store.py`)

```python
from invoiceflow import store, models
from invoiceflow.schema import InvoiceFields, Vendor


def test_create_and_find_job(db):
    jid = store.create_job("folder", "/x/a.pdf", "hash123", "/enc/a.bin")
    assert isinstance(jid, int)
    assert store.find_job_by_hash("hash123").id == jid
    assert store.find_job_by_hash("nope") is None


def test_save_and_get_invoice_roundtrip(db):
    jid = store.create_job("folder", "/x/a.pdf", "h", "/enc/a.bin")
    fields = InvoiceFields(invoice_number="INV-1", total=120.0,
                           vendor=Vendor(name="Acme"))
    flags = {"total": {"confidence": "high", "reasons": []}}
    iid = store.save_invoice(jid, fields, flags, "high")
    got = store.get_invoice(iid)
    assert got.fields.invoice_number == "INV-1"
    assert got.fields.vendor.name == "Acme"
    assert got.flags["total"]["confidence"] == "high"
    assert got.status == models.NEEDS_REVIEW


def test_list_invoices_by_status(db):
    jid = store.create_job("folder", "/x/a.pdf", "h", "/enc/a.bin")
    store.save_invoice(jid, InvoiceFields(), {}, "low")
    rows = store.list_invoices(status=models.NEEDS_REVIEW)
    assert len(rows) == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_store.py -v`
Expected: FAIL (no module/attr `store.create_job`).

- [ ] **Step 4: Write `store.py`**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add invoiceflow/store.py tests/conftest.py tests/test_store.py
git commit -m "feat: encrypted store (jobs + invoices)"
```

---

### Task 7: Queue (atomic SQLite claim)

**Files:**
- Create: `invoiceflow/queue.py`, `tests/test_queue.py`

- [ ] **Step 1: Write the failing test** (`tests/test_queue.py`)

```python
from invoiceflow import store, queue
from invoiceflow.models import PROCESSING
from invoiceflow.db import SessionLocal
from invoiceflow.models import Job


def test_claim_returns_pending_then_none(db):
    j1 = store.create_job("folder", "a", "h1", "/e1")
    j2 = store.create_job("folder", "b", "h2", "/e2")
    claimed = [queue.claim_next_job("w1"), queue.claim_next_job("w1")]
    assert set(claimed) == {j1, j2}
    assert queue.claim_next_job("w1") is None  # nothing left pending


def test_claimed_job_marked_processing(db):
    jid = store.create_job("folder", "a", "h1", "/e1")
    queue.claim_next_job("w1")
    with SessionLocal() as s:
        assert s.get(Job, jid).status == PROCESSING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_queue.py -v`
Expected: FAIL (no `queue.claim_next_job`).

- [ ] **Step 3: Write `queue.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import text

from invoiceflow.db import get_engine
from invoiceflow.models import PENDING, PROCESSING


def claim_next_job(worker_id: str) -> int | None:
    """Atomically claim the oldest pending job. Returns job id or None."""
    now = datetime.now(timezone.utc).isoformat()
    with get_engine().begin() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        row = conn.execute(
            text(
                "UPDATE jobs SET status=:proc, worker_id=:w, started_at=:t "
                "WHERE id = (SELECT id FROM jobs WHERE status=:pend "
                "ORDER BY created_at LIMIT 1) RETURNING id"
            ),
            {"proc": PROCESSING, "w": worker_id, "t": now, "pend": PENDING},
        ).fetchone()
    return row[0] if row else None
```

- [ ] **Step 4: Add `worker_id` column to `Job`**

Modify `invoiceflow/models.py` — add to class `Job` (after `attempts`):
```python
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_queue.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add invoiceflow/queue.py invoiceflow/models.py tests/test_queue.py
git commit -m "feat: atomic sqlite job queue"
```

---

### Task 8: Ingest (FolderSource)

**Files:**
- Create: `invoiceflow/ingest.py`, `tests/test_ingest.py`

- [ ] **Step 1: Write the failing test** (`tests/test_ingest.py`)

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL (no `ingest.FolderSource`).

- [ ] **Step 3: Write `ingest.py`**

```python
import hashlib
from pathlib import Path

from invoiceflow import crypto, store
from invoiceflow.config import Settings


class FolderSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def hash_file(path: Path) -> str:
        h = hashlib.sha256()
        h.update(Path(path).read_bytes())
        return h.hexdigest()

    def ingest_file(self, path: Path) -> int | None:
        path = Path(path)
        digest = self.hash_file(path)
        if store.find_job_by_hash(digest) is not None:
            return None  # duplicate
        enc_path = self.settings.store_dir / f"{digest}.bin"
        enc_path.write_bytes(crypto.encrypt(path.read_bytes()))
        return store.create_job("folder", str(path), digest, str(enc_path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add invoiceflow/ingest.py tests/test_ingest.py
git commit -m "feat: folder ingest with dedup + encryption"
```

---

### Task 9: Reader (PDF text vs OCR routing)

**Files:**
- Create: `invoiceflow/reader.py`, `tests/test_reader.py`

- [ ] **Step 1: Write the failing test** (`tests/test_reader.py`)

```python
import fitz  # PyMuPDF

from invoiceflow import reader
from invoiceflow.config import get_settings


def _make_text_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "INVOICE INV-42 TOTAL 99.00")
    return doc.tobytes()


def test_digital_pdf_uses_text_not_ocr(tmp_path):
    s = get_settings(str(tmp_path))
    result = reader.read_document(_make_text_pdf(), "a.pdf", s)
    assert "INV-42" in result.full_text
    assert result.used_ocr is False


def test_imageonly_pdf_routes_to_ocr(tmp_path, monkeypatch):
    s = get_settings(str(tmp_path))
    # blank PDF (no text layer) → OCR path; stub OCR to avoid tesseract dep in unit test
    monkeypatch.setattr(reader, "_ocr_page", lambda pix, lang: "OCR TEXT INV-7")
    blank = fitz.open()
    blank.new_page()
    result = reader.read_document(blank.tobytes(), "scan.pdf", s)
    assert result.used_ocr is True
    assert "INV-7" in result.full_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reader.py -v`
Expected: FAIL (no `reader.read_document`).

- [ ] **Step 3: Write `reader.py`**

```python
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from invoiceflow.config import Settings


@dataclass
class Page:
    text: str
    boxes: list = field(default_factory=list)  # [(word, x0,y0,x1,y1)] when OCR


@dataclass
class ReaderResult:
    pages: list[Page]
    full_text: str
    used_ocr: bool


def _ocr_page(pix: "fitz.Pixmap", lang: str) -> str:
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(img, lang=lang)


def read_document(data: bytes, filename: str, settings: Settings) -> ReaderResult:
    doc = fitz.open(stream=data, filetype="pdf" if filename.lower().endswith(".pdf") else None)
    pages: list[Page] = []
    used_ocr = False
    for page in doc:
        text = page.get_text().strip()
        if len(text) >= settings.text_threshold:
            pages.append(Page(text=text))
        else:
            used_ocr = True
            pix = page.get_pixmap(dpi=200)
            pages.append(Page(text=_ocr_page(pix, settings.ocr_lang).strip()))
    full = "\n".join(p.text for p in pages)
    return ReaderResult(pages=pages, full_text=full, used_ocr=used_ocr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reader.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add invoiceflow/reader.py tests/test_reader.py
git commit -m "feat: reader with pdf-text/ocr routing"
```

---

### Task 10: Extractor (Ollama structured JSON)

**Files:**
- Create: `invoiceflow/extractor.py`, `tests/test_extractor.py`

- [ ] **Step 1: Write the failing test** (`tests/test_extractor.py`)

```python
import json

from invoiceflow import extractor
from invoiceflow.config import get_settings


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self): pass
    def json(self): return self._payload


def test_extract_parses_model_json(monkeypatch, tmp_path):
    s = get_settings(str(tmp_path))
    content = json.dumps({"invoice_number": "INV-9", "total": 50.0,
                          "vendor": {"name": "Acme"}})
    monkeypatch.setattr(extractor.httpx, "post",
                        lambda *a, **k: _FakeResp({"message": {"content": content}}))
    fields = extractor.extract_fields("INVOICE INV-9 total 50.00", s)
    assert fields.invoice_number == "INV-9"
    assert fields.total == 50.0
    assert fields.vendor.name == "Acme"


def test_extract_raises_on_bad_json(monkeypatch, tmp_path):
    s = get_settings(str(tmp_path))
    monkeypatch.setattr(extractor.httpx, "post",
                        lambda *a, **k: _FakeResp({"message": {"content": "not json"}}))
    try:
        extractor.extract_fields("x", s)
        assert False, "expected ExtractionError"
    except extractor.ExtractionError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extractor.py -v`
Expected: FAIL (no `extractor.extract_fields`).

- [ ] **Step 3: Write `extractor.py`**

```python
import json

import httpx

from invoiceflow.config import Settings
from invoiceflow.schema import INVOICE_JSON_SCHEMA, InvoiceFields

_SYS = (
    "You extract structured data from invoice text. "
    "Return ONLY fields supported by the text. Use empty string / null when unknown. "
    "Never invent values that are not present."
)


class ExtractionError(Exception):
    pass


def extract_fields(text: str, settings: Settings) -> InvoiceFields:
    body = {
        "model": settings.model,
        "stream": False,
        "format": INVOICE_JSON_SCHEMA,
        "messages": [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": f"Invoice text:\n\n{text}"},
        ],
    }
    try:
        resp = httpx.post(f"{settings.ollama_url}/api/chat", json=body, timeout=120)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return InvoiceFields.model_validate_json(content)
    except (httpx.HTTPError, KeyError) as e:
        raise ExtractionError(f"ollama call failed: {e}") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise ExtractionError(f"invalid model JSON: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_extractor.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add invoiceflow/extractor.py tests/test_extractor.py
git commit -m "feat: ollama structured-json extractor"
```

---

### Task 11: Validator (rule-based confidence)

**Files:**
- Create: `invoiceflow/validator.py`, `tests/test_validator.py`

- [ ] **Step 1: Write the failing test** (`tests/test_validator.py`)

```python
from invoiceflow import validator
from invoiceflow.schema import InvoiceFields, LineItem


def test_arithmetic_consistent_is_high():
    f = InvoiceFields(invoice_number="INV-1", subtotal=100.0, tax=20.0, total=120.0,
                      line_items=[LineItem(amount=100.0)])
    text = "INV-1 subtotal 100.00 tax 20.00 total 120.00"
    flags, summary = validator.validate(f, text)
    assert flags["total"]["confidence"] == "high"
    assert summary == "high"


def test_total_mismatch_flags_low():
    f = InvoiceFields(invoice_number="INV-1", subtotal=100.0, tax=20.0, total=999.0,
                      line_items=[LineItem(amount=100.0)])
    text = "INV-1 subtotal 100.00 tax 20.00 total 999.00"
    flags, summary = validator.validate(f, text)
    assert flags["total"]["confidence"] == "low"
    assert "arithmetic" in flags["total"]["reasons"]


def test_value_not_in_text_is_low_grounding():
    f = InvoiceFields(invoice_number="INV-HALLUCINATED")
    text = "some invoice text without that number"
    flags, summary = validator.validate(f, text)
    assert flags["invoice_number"]["confidence"] == "low"
    assert "not_in_source" in flags["invoice_number"]["reasons"]


def test_missing_required_is_low():
    f = InvoiceFields()  # empty
    flags, summary = validator.validate(f, "")
    assert flags["invoice_number"]["confidence"] == "low"
    assert "missing" in flags["invoice_number"]["reasons"]
    assert summary == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validator.py -v`
Expected: FAIL (no `validator.validate`).

- [ ] **Step 3: Write `validator.py`**

```python
import re

from invoiceflow.schema import InvoiceFields

_REQUIRED = ["invoice_number", "invoice_date", "total"]
_TOL = 0.01


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _grounded(value, source_norm: str) -> bool:
    if value is None or value == "":
        return False
    return _norm(str(value)) in source_norm


def validate(fields: InvoiceFields, source_text: str) -> tuple[dict, str]:
    src = _norm(source_text)
    flags: dict = {}

    def mark(field, value, *, required=False):
        reasons = []
        if value in (None, ""):
            if required:
                reasons.append("missing")
        elif not _grounded(value, src):
            reasons.append("not_in_source")
        flags[field] = {"confidence": "low" if reasons else "high", "reasons": reasons}

    mark("invoice_number", fields.invoice_number, required=True)
    mark("invoice_date", fields.invoice_date, required=True)
    mark("total", fields.total, required=True)
    mark("subtotal", fields.subtotal)
    mark("tax", fields.tax)
    mark("vendor_name", fields.vendor.name)

    # arithmetic cross-checks override grounding for the involved fields
    if fields.subtotal is not None and fields.tax is not None and fields.total is not None:
        if abs((fields.subtotal + fields.tax) - fields.total) > _TOL:
            flags["total"] = {"confidence": "low", "reasons": ["arithmetic"]}
    line_sum = sum(li.amount for li in fields.line_items if li.amount is not None)
    if fields.line_items and fields.subtotal is not None:
        if abs(line_sum - fields.subtotal) > _TOL:
            flags["subtotal"] = {"confidence": "low",
                                 "reasons": flags.get("subtotal", {}).get("reasons", []) + ["arithmetic"]}

    summary = "low" if any(v["confidence"] == "low" for v in flags.values()) else "high"
    return flags, summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validator.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add invoiceflow/validator.py tests/test_validator.py
git commit -m "feat: rule-based confidence validator"
```

---

### Task 12: Worker (orchestration)

**Files:**
- Create: `invoiceflow/worker.py`, `tests/test_worker.py`

- [ ] **Step 1: Write the failing test** (`tests/test_worker.py`)

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL (no `worker.process_job`).

- [ ] **Step 3: Write `worker.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add invoiceflow/worker.py tests/test_worker.py
git commit -m "feat: worker orchestration with failure capture"
```

---

### Task 13: CLI (watch / work / list)

**Files:**
- Create: `invoiceflow/cli.py`

- [ ] **Step 1: Write `cli.py`**

```python
import argparse
import time
from pathlib import Path

from invoiceflow import ingest, queue, store, worker
from invoiceflow.config import get_settings, ensure_dirs
from invoiceflow.db import init_db


def _scan_inbox(settings, src) -> None:
    for p in Path(settings.inbox_dir).glob("*"):
        if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"):
            jid = src.ingest_file(p)
            if jid:
                print(f"ingested {p.name} -> job {jid}")


def cmd_watch(settings) -> None:
    src = ingest.FolderSource(settings)
    print(f"watching {settings.inbox_dir} (Ctrl-C to stop)")
    while True:
        _scan_inbox(settings, src)
        time.sleep(3)


def cmd_work(settings, once: bool) -> None:
    while True:
        jid = queue.claim_next_job("cli")
        if jid is None:
            if once:
                break
            time.sleep(2)
            continue
        print(f"processing job {jid} ...")
        worker.process_job(jid, settings)
    print("no pending jobs")


def cmd_list(settings, status: str | None) -> None:
    for inv in store.list_invoices(status=status):
        print(f"#{inv.id}\t{inv.status}\t{inv.confidence_summary}\tjob={inv.job_id}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="invoiceflow")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("watch")
    w = sub.add_parser("work")
    w.add_argument("--once", action="store_true")
    li = sub.add_parser("list")
    li.add_argument("--status", default=None)
    args = parser.parse_args()

    settings = get_settings()
    ensure_dirs(settings)
    init_db(settings)

    if args.cmd == "watch":
        cmd_watch(settings)
    elif args.cmd == "work":
        cmd_work(settings, once=args.once)
    elif args.cmd == "list":
        cmd_list(settings, status=args.status)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual end-to-end smoke test (requires Ollama + model)**

Run:
```bash
ollama pull qwen2.5:14b
mkdir -p ~/.invoiceflow/inbox
cp some_invoice.pdf ~/.invoiceflow/inbox/
invoiceflow watch &          # ingests the file -> a job
invoiceflow work --once      # processes pending jobs
invoiceflow list             # shows the invoice + confidence summary
```
Expected: `list` prints one invoice row with status `needs_review`.

- [ ] **Step 3: Commit**

```bash
git add invoiceflow/cli.py
git commit -m "feat: cli (watch/work/list)"
```

---

### Task 14: Full test sweep + golden sample

**Files:**
- Create: `tests/fixtures/README.md`

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: all tests PASS (crypto, store, queue, ingest, reader, extractor, validator, worker).

- [ ] **Step 2: Document the golden-set convention**

`tests/fixtures/README.md`:
```markdown
# Golden samples
Drop real sample invoices here (digital PDF + scanned). For each `name.pdf`,
add `name.expected.json` matching the InvoiceFields schema. A future
`test_golden.py` will assert extraction accuracy against these (Phase 2).
```

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/README.md
git commit -m "test: full sweep green + golden-set convention"
```

---

## Self-review notes
- **Spec coverage:** ingest §3.1 (T8), queue §3.2 (T7), reader §3.3 (T9), extractor §3.4 (T10), validator §3.5 (T11), store/crypto/db §3.6 (T2–T4,T6), worker §3.9 (T12), CLI (T13). Review UI/exporter/email = Phase 2/3 (out of scope, stated).
- **Types consistent across tasks:** `InvoiceFields`/`Vendor`/`LineItem` (schema), `ReaderResult`/`Page` (reader), `ExtractionError` (extractor), `claim_next_job` (queue), `process_job` (worker), `LoadedInvoice` (store). `Job.worker_id` added in T7 before queue uses it.
- **No placeholders:** every code/test step has full content; commands have expected output.
- **Known Phase-2 follow-ups:** OCR bounding boxes are stubbed (`Page.boxes` empty for the text path) — populated when the Review UI needs region highlighting; `validator` grounding uses normalized substring match (intentionally simple).
```
