# local-invoice-ocr

Fully **local** invoice processing: reads PDFs/scans, extracts structured data with a
local LLM, scores confidence with rules, and stores everything **encrypted** in SQLite.
Nothing leaves the machine — all processing runs on your Mac (Apple Silicon).

> Status: **Phase 1 (MVP)** — end-to-end pipeline `ingest → reader → extractor → validator → store` + CLI. 20 tests passing.
> Next: Review UI (Phase 2), email intake + export to an external system (Phase 3).

---

## How it works

```
inbox folder ─▶ ingest ─▶ queue ─▶ worker ─▶ reader ─▶ extractor ─▶ validator ─▶ store ─▶ (Review UI / export)
                hash+dedup  (SQLite)          PDF/OCR    Ollama JSON   confidence   SQLite+encrypt
                encrypt file                                                          needs_review
```

| Stage | What it does |
|---|---|
| **ingest** | SHA-256 + dedup, encrypts the original (AES-256-GCM), creates a job |
| **queue** | atomic job claim from SQLite (WAL) |
| **reader** | digital PDF → text (PyMuPDF); scan/photo → Tesseract OCR |
| **extractor** | text → strict invoice-schema JSON via a local Ollama model |
| **validator** | rule-based confidence: arithmetic (Σ line items = subtotal, subtotal+tax = total), date/number parsing, **grounding** (value appears verbatim in the source text — anti-hallucination), required fields |
| **store** | SQLite; sensitive fields and originals encrypted, key in macOS Keychain; `audit_log` |

Fields that fail the checks are flagged `low` — visible in the list now, and highlighted in the side-by-side review (Phase 2).

## Privacy

- **Local only:** network access is `localhost` (Ollama) only.
- **At rest:** original files and sensitive DB fields are AES-256-GCM encrypted; the master key lives in the **macOS Keychain**, never in the repo.
- **Audit:** `audit_log` records who/what/when (values encrypted).
- `.gitignore` excludes the DB and temp files; keys are never committed.

## Requirements

- macOS (Apple Silicon recommended)
- **Python 3.11+** (tested on 3.12)
- **Tesseract** (`brew install tesseract`)
- **Ollama** with an extraction model (e.g. `qwen2.5:14b`) — required to actually run the extractor

## Installation

```bash
brew install tesseract
# Python 3.12 (if your system Python lacks wheels for the deps):
brew install python@3.12

git clone https://github.com/ljutaev/local-invoice-ocr.git
cd local-invoice-ocr
/opt/homebrew/opt/python@3.12/libexec/bin/python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# extraction model
ollama pull qwen2.5:14b
```

## Usage

```bash
# 1. drop invoices into the inbox
mkdir -p ~/.invoiceflow/inbox
cp invoice1.pdf scan2.jpg ~/.invoiceflow/inbox/

# 2. pick up new files into the queue (background watcher)
invoiceflow watch &

# 3. process the queue
invoiceflow work --once        # single pass; omit --once to run continuously

# 4. inspect results
invoiceflow list                       # all
invoiceflow list --status needs_review # only those needing review
```

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `INVOICEFLOW_HOME` | `~/.invoiceflow` | base dir (inbox, store, DB) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama address |
| `INVOICEFLOW_MODEL` | `qwen2.5:14b` | extraction model |
| `INVOICEFLOW_OCR_LANG` | `eng` | Tesseract language |
| `INVOICEFLOW_TEXT_THRESHOLD` | `100` | min chars/page to treat a PDF as digital (else OCR) |
| `INVOICEFLOW_MAX_ATTEMPTS` | `3` | job processing attempts |

## Project layout

```
invoiceflow/        package
  config.py         settings
  crypto.py         AES-256-GCM + Keychain key
  db.py models.py   SQLite (WAL) + ORM
  schema.py         pydantic invoice schema + JSON schema for Ollama
  store.py queue.py persistence + queue
  ingest.py reader.py extractor.py validator.py worker.py
  cli.py            watch / work / list
tests/              pytest (20 tests)
docs/superpowers/   design doc + implementation plan
```

## Tests

```bash
source .venv/bin/activate
pytest            # 20 passed
```
Unit tests mock Ollama and Tesseract, so they pass without them; a full end-to-end run requires a running Ollama with the model.

## Roadmap

- [x] **Phase 1** — ingest→store pipeline + CLI (current)
- [ ] **Phase 2** — Review UI (FastAPI + PDF.js): original ↔ fields, low-confidence highlighting, editing, approve, audit; web upload
- [ ] **Phase 3** — email intake (IMAP) + `Exporter` (CSV/JSON → ERP/API)
