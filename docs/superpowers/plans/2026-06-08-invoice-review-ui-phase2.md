# Invoice Review UI — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]` checkboxes.

**Goal:** A local web app to review extracted invoices side-by-side with the original document, edit fields, approve, and upload new invoices — all on localhost, decrypting in memory only.

**Architecture:** FastAPI + Jinja2 server-rendered pages. The original (encrypted on disk) is decrypted in-memory and streamed to the browser, which renders PDFs natively (iframe) and images (`<img>`) — no external/CDN assets, stays offline. Extracted fields render as an editable form; low-confidence fields are highlighted. Editing writes an encrypted audit trail; approve flips status to `verified`.

**Tech Stack:** FastAPI, uvicorn, Jinja2, python-multipart (uploads), Starlette TestClient for tests. Reuses Phase 1 `store`/`crypto`/`ingest`/`db`.

---

## Spec → Plan mapping
- §3.7 Review UI (list, side-by-side detail, low-confidence highlight, edit, approve, audit) → Tasks 6–11
- §3.1 web upload (`UploadSource`) → Task 5
- §3.6 audit on edit/approve → Tasks 2,3
- **Also fixes a latent Phase-1 bug:** `cli.cmd_list` accessed ORM attributes after the session closed (DetachedInstanceError when rows exist). Task 4 adds session-scoped summaries and Task 12 switches the CLI to them.
- **Deferred (documented):** OCR region overlay (click field → highlight box on document) and per-line-item editing — Phase 2 highlights fields in the form and shows the document beside it; box overlays/line-item edit are a later enhancement.

## File structure
```
invoiceflow/
  webapp.py              FastAPI app factory + routes
  templates/
    base.html            layout
    list.html            invoice list + upload form
    detail.html          side-by-side review + edit/approve
  static/
    style.css            minimal styling, low-confidence highlight
  store.py     (modify)  + list_invoice_summaries, update_invoice_fields, approve_invoice, get_original_bytes
  ingest.py    (modify)  + UploadSource.ingest_bytes (shared _ingest_bytes helper)
  cli.py       (modify)  + `serve` command; cmd_list uses summaries
pyproject.toml (modify)  + fastapi, uvicorn, jinja2, python-multipart
tests/
  test_store_phase2.py   store additions
  test_ingest_upload.py  UploadSource
  test_webapp.py         routes via TestClient
```

---

### Task 1: Add web dependencies

**Files:** Modify `pyproject.toml`

- [ ] **Step 1: Add deps** — in `[project].dependencies` append:
```toml
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
```

- [ ] **Step 2: Install** — Run: `pip install -e ".[dev]"` · Expected: success.

- [ ] **Step 3: Commit**
```bash
git add pyproject.toml
git commit -m "chore: add web deps for review ui"
```

---

### Task 2: store.update_invoice_fields (+ audit)

**Files:** Modify `invoiceflow/store.py`; Create `tests/test_store_phase2.py`

- [ ] **Step 1: Write failing test** (`tests/test_store_phase2.py`)
```python
import json
from invoiceflow import store, crypto
from invoiceflow.db import SessionLocal
from invoiceflow.models import AuditLog
from invoiceflow.schema import InvoiceFields, Vendor


def test_update_writes_fields_and_audit(db):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="INV-1", total=10.0), {}, "high")
    store.update_invoice_fields(iid, InvoiceFields(invoice_number="INV-1", total=12.5,
                                                   vendor=Vendor(name="Acme")), user="me")
    got = store.get_invoice(iid)
    assert got.fields.total == 12.5
    assert got.fields.vendor.name == "Acme"
    with SessionLocal() as s:
        logs = s.query(AuditLog).filter(AuditLog.invoice_id == iid).all()
        changed = {l.field for l in logs}
        assert "total" in changed and "vendor" in changed
        # audit values are encrypted
        tot = next(l for l in logs if l.field == "total")
        assert json.loads(crypto.decrypt_str(tot.enc_new)) == 12.5
```

- [ ] **Step 2: Run → fail** · `pytest tests/test_store_phase2.py::test_update_writes_fields_and_audit -v` · Expected: FAIL (no `update_invoice_fields`).

- [ ] **Step 3: Implement** — add to `invoiceflow/store.py` (add imports `import json`, `from datetime import datetime, timezone`, `from pathlib import Path`, and `from invoiceflow.models import AuditLog, VERIFIED, Job` to the existing model import):
```python
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
```

- [ ] **Step 4: Run → pass** · same command · Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add invoiceflow/store.py tests/test_store_phase2.py
git commit -m "feat: store.update_invoice_fields with encrypted audit"
```

---

### Task 3: store.approve_invoice

**Files:** Modify `invoiceflow/store.py`; append to `tests/test_store_phase2.py`

- [ ] **Step 1: Add failing test**
```python
def test_approve_sets_verified(db):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="INV-1"), {}, "low")
    store.approve_invoice(iid, user="me")
    got = store.get_invoice(iid)
    assert got.status == "verified"
    with SessionLocal() as s:
        from invoiceflow.models import Invoice as I
        assert s.get(I, iid).verified_by == "me"
```

- [ ] **Step 2: Run → fail** · `pytest tests/test_store_phase2.py::test_approve_sets_verified -v`.

- [ ] **Step 3: Implement** — add to `store.py`:
```python
def approve_invoice(invoice_id: int, user: str) -> None:
    with SessionLocal() as s:
        inv = s.get(Invoice, invoice_id)
        inv.status = VERIFIED
        inv.verified_at = datetime.now(timezone.utc)
        inv.verified_by = user
        s.add(AuditLog(invoice_id=invoice_id, action="approve", user=user))
        s.commit()
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit**
```bash
git add invoiceflow/store.py tests/test_store_phase2.py
git commit -m "feat: store.approve_invoice"
```

---

### Task 4: store.list_invoice_summaries + get_original_bytes

**Files:** Modify `invoiceflow/store.py`; append to `tests/test_store_phase2.py`

- [ ] **Step 1: Add failing tests**
```python
def test_summaries_decrypt_within_session(db):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    store.save_invoice(jid, InvoiceFields(invoice_number="INV-7", total=5.0,
                                          vendor=Vendor(name="Acme")), {}, "high")
    rows = store.list_invoice_summaries()
    assert rows[0]["invoice_number"] == "INV-7"
    assert rows[0]["vendor"] == "Acme"
    assert rows[0]["total"] == 5.0


def test_get_original_bytes_roundtrip(db, settings, tmp_path):
    enc_path = tmp_path / "x.bin"
    enc_path.write_bytes(crypto.encrypt(b"%PDF-1.4 hello"))
    jid = store.create_job("folder", "x.pdf", "h2", str(enc_path))
    iid = store.save_invoice(jid, InvoiceFields(), {}, "low")
    data, media = store.get_original_bytes(iid)
    assert data == b"%PDF-1.4 hello"
    assert media == "application/pdf"
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — add to `store.py`:
```python
_MEDIA = {".pdf": "application/pdf", ".png": "image/png",
          ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


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


def get_original_bytes(invoice_id: int) -> tuple[bytes, str]:
    with SessionLocal() as s:
        inv = s.get(Invoice, invoice_id)
        job = s.get(Job, inv.job_id)
        enc = Path(job.enc_file_path).read_bytes()
        data = crypto.decrypt(enc)
        ext = Path(job.source_ref).suffix.lower()
    return data, _MEDIA.get(ext, "application/octet-stream")
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit**
```bash
git add invoiceflow/store.py tests/test_store_phase2.py
git commit -m "feat: store summaries + original-bytes accessor"
```

---

### Task 5: ingest.UploadSource

**Files:** Modify `invoiceflow/ingest.py`; Create `tests/test_ingest_upload.py`

- [ ] **Step 1: Write failing test**
```python
from invoiceflow import ingest, store, crypto
from pathlib import Path


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
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — rewrite `invoiceflow/ingest.py` to share a helper:
```python
import hashlib
from pathlib import Path

from invoiceflow import crypto, store
from invoiceflow.config import Settings


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ingest_bytes(settings: Settings, source: str, source_ref: str, data: bytes) -> int | None:
    digest = _sha256(data)
    if store.find_job_by_hash(digest) is not None:
        return None
    enc_path = settings.store_dir / f"{digest}.bin"
    enc_path.write_bytes(crypto.encrypt(data))
    return store.create_job(source, source_ref, digest, str(enc_path))


class FolderSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def hash_file(path: Path) -> str:
        return _sha256(Path(path).read_bytes())

    def ingest_file(self, path: Path) -> int | None:
        path = Path(path)
        return _ingest_bytes(self.settings, "folder", str(path), path.read_bytes())


class UploadSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    def ingest_bytes(self, data: bytes, filename: str) -> int | None:
        return _ingest_bytes(self.settings, "upload", filename, data)
```

- [ ] **Step 4: Run → pass** (and `pytest tests/test_ingest.py -v` still PASS — FolderSource unchanged behavior).

- [ ] **Step 5: Commit**
```bash
git add invoiceflow/ingest.py tests/test_ingest_upload.py
git commit -m "feat: UploadSource via shared ingest helper"
```

---

### Task 6: webapp factory + list route

**Files:** Create `invoiceflow/webapp.py`, `invoiceflow/templates/base.html`, `invoiceflow/templates/list.html`, `invoiceflow/static/style.css`, `tests/test_webapp.py`

- [ ] **Step 1: Write failing test** (`tests/test_webapp.py`)
```python
import os
import pytest
from starlette.testclient import TestClient

from invoiceflow import crypto, store, webapp
from invoiceflow.config import get_settings
from invoiceflow.db import init_db
from invoiceflow.schema import InvoiceFields, Vendor


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "get_key", lambda: os.urandom(32))
    s = get_settings(str(tmp_path))
    init_db(s)
    return TestClient(webapp.create_app(s))


def test_list_page_shows_invoices(client):
    jid = store.create_job("folder", "a.pdf", "h", "/e")
    store.save_invoice(jid, InvoiceFields(invoice_number="INV-LIST",
                                          vendor=Vendor(name="Acme")), {}, "low")
    r = client.get("/")
    assert r.status_code == 200
    assert "INV-LIST" in r.text
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `invoiceflow/webapp.py`**
```python
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from invoiceflow import ingest, store
from invoiceflow.config import Settings, ensure_dirs
from invoiceflow.db import init_db
from invoiceflow.schema import InvoiceFields, Vendor

_DIR = Path(__file__).parent
_USER = "reviewer"  # single-user local app for now

# scalar fields editable in the MVP form (line items shown read-only)
_EDIT_FIELDS = ["invoice_number", "invoice_date", "due_date", "buyer_name",
                "currency", "subtotal", "tax", "total", "po_number", "payment_terms"]
_NUMERIC = {"subtotal", "tax", "total"}


def create_app(settings: Settings) -> FastAPI:
    ensure_dirs(settings)
    init_db(settings)
    app = FastAPI(title="local-invoice-ocr")
    templates = Jinja2Templates(directory=str(_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, status: str | None = None):
        rows = store.list_invoice_summaries(status=status)
        return templates.TemplateResponse("list.html",
                                          {"request": request, "rows": rows, "status": status})

    @app.get("/invoice/{invoice_id}", response_class=HTMLResponse)
    def detail(request: Request, invoice_id: int):
        inv = store.get_invoice(invoice_id)
        return templates.TemplateResponse("detail.html", {
            "request": request, "inv": inv, "fields": inv.fields,
            "flags": inv.flags, "edit_fields": _EDIT_FIELDS,
        })

    @app.get("/invoice/{invoice_id}/file")
    def original(invoice_id: int):
        data, media = store.get_original_bytes(invoice_id)
        return Response(content=data, media_type=media)

    @app.post("/invoice/{invoice_id}")
    async def save(invoice_id: int, request: Request):
        form = await request.form()
        cur = store.get_invoice(invoice_id).fields
        data = cur.model_dump()
        for k in _EDIT_FIELDS:
            v = form.get(k)
            if v is None:
                continue
            v = v.strip()
            if k in _NUMERIC:
                data[k] = float(v) if v else None
            else:
                data[k] = v
        data["vendor"] = {
            "name": (form.get("vendor_name") or "").strip(),
            "address": (form.get("vendor_address") or "").strip(),
            "tax_id": (form.get("vendor_tax_id") or "").strip(),
        }
        store.update_invoice_fields(invoice_id, InvoiceFields(**data), _USER)
        return RedirectResponse(f"/invoice/{invoice_id}", status_code=303)

    @app.post("/invoice/{invoice_id}/approve")
    def approve(invoice_id: int):
        store.approve_invoice(invoice_id, _USER)
        return RedirectResponse("/", status_code=303)

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        ingest.UploadSource(settings).ingest_bytes(await file.read(), file.filename)
        return RedirectResponse("/", status_code=303)

    return app
```

- [ ] **Step 4: Create `invoiceflow/templates/base.html`**
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>local-invoice-ocr</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header><a href="/"><strong>local-invoice-ocr</strong></a></header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

- [ ] **Step 5: Create `invoiceflow/templates/list.html`**
```html
{% extends "base.html" %}
{% block content %}
<h1>Invoices</h1>
<form action="/upload" method="post" enctype="multipart/form-data" class="upload">
  <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg" required>
  <button type="submit">Upload</button>
</form>
<p class="filters">
  <a href="/">all</a> ·
  <a href="/?status=needs_review">needs review</a> ·
  <a href="/?status=verified">verified</a>
</p>
<table>
  <tr><th>#</th><th>Invoice</th><th>Vendor</th><th>Total</th><th>Status</th><th>Confidence</th></tr>
  {% for r in rows %}
  <tr class="{{ 'low' if r.summary == 'low' else '' }}">
    <td><a href="/invoice/{{ r.id }}">{{ r.id }}</a></td>
    <td>{{ r.invoice_number }}</td><td>{{ r.vendor }}</td><td>{{ r.total }}</td>
    <td>{{ r.status }}</td><td>{{ r.summary }}</td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 6: Create `invoiceflow/static/style.css`**
```css
body { font-family: -apple-system, sans-serif; margin: 0; color: #1a1a2e; }
header { background: #4f46e5; padding: 10px 18px; }
header a { color: #fff; text-decoration: none; }
main { padding: 18px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #e2e2ec; padding: 6px 10px; text-align: left; }
th { background: #4f46e5; color: #fff; }
tr.low td { background: #fff7ed; }
.filters { margin: 10px 0; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.doc iframe, .doc img { width: 100%; height: 80vh; border: 1px solid #e2e2ec; }
.field.low input { background: #fef2f2; border: 1px solid #dc2626; }
.field label { display: block; font-size: 12px; color: #555; margin-top: 8px; }
.field input { width: 100%; padding: 5px; }
.reasons { color: #b91c1c; font-size: 11px; }
button { background: #4f46e5; color: #fff; border: 0; padding: 8px 14px; border-radius: 6px; cursor: pointer; }
.approve { background: #16a34a; }
</style>
```
> Note: remove the trailing `</style>` line — CSS files contain no tags. Save only the CSS rules above.

- [ ] **Step 7: Run → pass** · `pytest tests/test_webapp.py::test_list_page_shows_invoices -v`.

- [ ] **Step 8: Commit**
```bash
git add invoiceflow/webapp.py invoiceflow/templates invoiceflow/static tests/test_webapp.py
git commit -m "feat: review ui app factory + list page"
```

---

### Task 7: detail page (side-by-side) template

**Files:** Create `invoiceflow/templates/detail.html`; append to `tests/test_webapp.py`

- [ ] **Step 1: Add failing tests**
```python
def test_detail_and_file(client):
    import os.path
    from pathlib import Path
    # build a job whose encrypted file we control
    s = client.app  # not used; create via store + a real enc file
    jid = store.create_job("upload", "a.pdf", "h", "/tmp/none")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="INV-DET", total=1.0),
                             {"total": {"confidence": "low", "reasons": ["arithmetic"]}}, "low")
    r = client.get(f"/invoice/{iid}")
    assert r.status_code == 200
    assert "INV-DET" in r.text
    assert "arithmetic" in r.text  # low-confidence reason shown
```

- [ ] **Step 2: Run → fail** (TemplateNotFound: detail.html).

- [ ] **Step 3: Create `invoiceflow/templates/detail.html`**
```html
{% extends "base.html" %}
{% block content %}
<p><a href="/">← back</a> · invoice #{{ inv.id }} · status: {{ inv.status }}</p>
<div class="split">
  <div class="doc">
    <iframe src="/invoice/{{ inv.id }}/file"></iframe>
  </div>
  <form method="post" action="/invoice/{{ inv.id }}">
    {% macro field(name, value) %}
      {% set fl = flags.get(name) %}
      <div class="field {{ 'low' if fl and fl.confidence == 'low' else '' }}">
        <label>{{ name }}</label>
        <input name="{{ name }}" value="{{ value if value is not none else '' }}">
        {% if fl and fl.reasons %}<div class="reasons">{{ fl.reasons|join(', ') }}</div>{% endif %}
      </div>
    {% endmacro %}
    {{ field('invoice_number', fields.invoice_number) }}
    {{ field('invoice_date', fields.invoice_date) }}
    {{ field('due_date', fields.due_date) }}
    <div class="field {{ 'low' if flags.get('vendor_name') and flags.get('vendor_name').confidence == 'low' else '' }}">
      <label>vendor_name</label>
      <input name="vendor_name" value="{{ fields.vendor.name }}">
    </div>
    <div class="field"><label>vendor_address</label>
      <input name="vendor_address" value="{{ fields.vendor.address }}"></div>
    <div class="field"><label>vendor_tax_id</label>
      <input name="vendor_tax_id" value="{{ fields.vendor.tax_id }}"></div>
    {{ field('buyer_name', fields.buyer_name) }}
    {{ field('currency', fields.currency) }}
    {{ field('subtotal', fields.subtotal) }}
    {{ field('tax', fields.tax) }}
    {{ field('total', fields.total) }}
    {{ field('po_number', fields.po_number) }}
    {{ field('payment_terms', fields.payment_terms) }}

    {% if fields.line_items %}
    <h3>Line items (read-only)</h3>
    <table>
      <tr><th>Description</th><th>Qty</th><th>Unit</th><th>Amount</th></tr>
      {% for li in fields.line_items %}
      <tr><td>{{ li.description }}</td><td>{{ li.qty }}</td>
          <td>{{ li.unit_price }}</td><td>{{ li.amount }}</td></tr>
      {% endfor %}
    </table>
    {% endif %}

    <p style="margin-top:14px">
      <button type="submit">Save</button>
      <button type="submit" formaction="/invoice/{{ inv.id }}/approve" class="approve">Approve</button>
    </p>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit**
```bash
git add invoiceflow/templates/detail.html tests/test_webapp.py
git commit -m "feat: side-by-side detail review page"
```

---

### Task 8: edit + approve + upload route tests

**Files:** append to `tests/test_webapp.py`

- [ ] **Step 1: Add failing tests**
```python
def test_save_edits_persists(client):
    jid = store.create_job("upload", "a.pdf", "h3", "/tmp/none")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="OLD", total=1.0), {}, "low")
    r = client.post(f"/invoice/{iid}",
                    data={"invoice_number": "NEW", "total": "9.99", "vendor_name": "Acme"},
                    follow_redirects=False)
    assert r.status_code == 303
    got = store.get_invoice(iid)
    assert got.fields.invoice_number == "NEW"
    assert got.fields.total == 9.99
    assert got.fields.vendor.name == "Acme"


def test_approve_route(client):
    jid = store.create_job("upload", "a.pdf", "h4", "/tmp/none")
    iid = store.save_invoice(jid, InvoiceFields(invoice_number="A"), {}, "low")
    r = client.post(f"/invoice/{iid}/approve", follow_redirects=False)
    assert r.status_code == 303
    assert store.get_invoice(iid).status == "verified"


def test_upload_route_creates_job(client):
    r = client.post("/upload", files={"file": ("u.pdf", b"%PDF-1.4 up", "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert store.find_job_by_hash(__import__("invoiceflow.ingest", fromlist=["_sha256"])._sha256(b"%PDF-1.4 up")) is not None
```

- [ ] **Step 2: Run → pass** (routes already implemented in Task 6) · `pytest tests/test_webapp.py -v`.

- [ ] **Step 3: Commit**
```bash
git add tests/test_webapp.py
git commit -m "test: edit/approve/upload routes"
```

---

### Task 9: CLI `serve` + fix cmd_list

**Files:** Modify `invoiceflow/cli.py`

- [ ] **Step 1: Replace `cmd_list`** body to use summaries (fixes DetachedInstanceError):
```python
def cmd_list(settings, status: str | None) -> None:
    for r in store.list_invoice_summaries(status=status):
        print(f"#{r['id']}\t{r['status']}\t{r['summary']}\t{r['invoice_number']}\t{r['vendor']}")
```

- [ ] **Step 2: Add `serve` command** — add to `main()` after the `list` subparser:
```python
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
```
and add a branch in the dispatch:
```python
    elif args.cmd == "serve":
        import uvicorn
        from invoiceflow.webapp import create_app
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
```

- [ ] **Step 3: Smoke** · Run: `invoiceflow list` · Expected: runs without DetachedInstanceError (empty or rows).

- [ ] **Step 4: Commit**
```bash
git add invoiceflow/cli.py
git commit -m "feat: cli serve + summary-based list (fixes detached attr access)"
```

---

### Task 10: Full sweep + manual UI check

**Files:** none

- [ ] **Step 1: Run all tests** · `pytest -v` · Expected: all PASS (Phase 1 + Phase 2).

- [ ] **Step 2: Manual UI smoke (with Ollama running + a processed invoice)**
```bash
invoiceflow serve            # open http://127.0.0.1:8000
# list shows invoices; click one → side-by-side; edit a field → Save; Approve
```
Expected: detail page shows the document on the left and editable fields on the right; low-confidence fields are highlighted; Save persists; Approve moves it to verified.

- [ ] **Step 3: Commit (if any docs/notes)** — otherwise done.

---

## Self-review notes
- **Spec coverage:** list + side-by-side detail + low-confidence highlight + edit + approve + audit (T2–T7), web upload (T5/T6), CLI serve (T9). Region/box overlay + per-line-item edit explicitly deferred.
- **Types consistent:** `InvoiceFields`/`Vendor` reused; new store fns `update_invoice_fields`, `approve_invoice`, `list_invoice_summaries`, `get_original_bytes`; `ingest._sha256`/`_ingest_bytes`/`UploadSource`. Route `_USER="reviewer"` used for audit.
- **No placeholders:** all routes, templates, css, and tests are complete. (CSS note in T6 step 6: drop the stray `</style>` line.)
- **Privacy preserved:** documents decrypted in-memory and streamed; browser-native rendering, no CDN/external assets; server binds `127.0.0.1` by default.
- **Bug fix folded in:** T9 fixes the latent Phase-1 `cmd_list` detached-attribute access.
```
