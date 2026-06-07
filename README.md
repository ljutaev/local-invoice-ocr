# local-invoice-ocr

Повністю **локальна** обробка інвойсів: читає PDF/скани, витягує структуровані дані
локальною LLM, оцінює впевненість за правилами і зберігає все **зашифрованим** у SQLite.
Жоден байт не залишає машину — обробка йде на вашому Mac (Apple Silicon).

> Статус: **Фаза 1 (MVP)** — наскрізний конвеєр `ingest → reader → extractor → validator → store` + CLI. 20 тестів зелені.
> Наступні фази: Review UI (Фаза 2), email-приймач + експорт у зовнішню систему (Фаза 3).

---

## Як це працює

```
тека-приймач ─▶ ingest ─▶ черга ─▶ worker ─▶ reader ─▶ extractor ─▶ validator ─▶ store ─▶ (Review UI / export)
               hash+дедуп   (SQLite)          PDF/OCR    Ollama JSON    впевненість   SQLite+шифр.
               шифрує файл                                                            needs_review
```

| Стадія | Що робить |
|---|---|
| **ingest** | SHA-256 + дедуп, шифрує оригінал (AES-256-GCM), створює job |
| **queue** | атомарне захоплення job із SQLite (WAL) |
| **reader** | цифровий PDF → текст (PyMuPDF); скан/фото → Tesseract OCR |
| **extractor** | текст → строгий JSON за схемою інвойсу через локальну Ollama |
| **validator** | впевненість **за правилами**: арифметика (Σ позицій = subtotal, subtotal+tax = total), парсинг дат/чисел, **grounding** (значення дослівно є в тексті — захист від галюцинацій), обов'язкові поля |
| **store** | SQLite; чутливі поля та оригінали зашифровані, ключ у macOS Keychain; `audit_log` |

Поля, що не пройшли перевірки, позначаються `low` — їх видно у списку (а у Фазі 2 — підсвічуватимуться в side-by-side перегляді).

## Приватність

- **Локально:** мережево лише `localhost` (Ollama).
- **At rest:** оригінали-файли та чутливі поля в БД зашифровані AES-256-GCM; майстер-ключ — у **macOS Keychain**, не в репозиторії.
- **Аудит:** `audit_log` фіксує хто/що/коли (значення зашифровані).
- `.gitignore` виключає БД і тимчасові файли; ключі ніколи не комітяться.

## Вимоги

- macOS (Apple Silicon рекомендовано)
- **Python 3.11+** (тестовано на 3.12)
- **Tesseract** (`brew install tesseract`)
- **Ollama** з моделлю для витягування (напр. `qwen2.5:14b`) — для реального запуску extractor

## Встановлення

```bash
brew install tesseract
# Python 3.12 (якщо системний несумісний з wheel'ами залежностей):
brew install python@3.12

git clone https://github.com/ljutaev/local-invoice-ocr.git
cd local-invoice-ocr
/opt/homebrew/opt/python@3.12/libexec/bin/python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# модель для витягування
ollama pull qwen2.5:14b
```

## Використання

```bash
# 1. покласти інвойси у теку-приймач
mkdir -p ~/.invoiceflow/inbox
cp invoice1.pdf scan2.jpg ~/.invoiceflow/inbox/

# 2. підхопити нові файли у чергу (фоновий watcher)
invoiceflow watch &

# 3. обробити чергу
invoiceflow work --once        # один прохід; без --once — безперервно

# 4. переглянути результати
invoiceflow list                       # усі
invoiceflow list --status needs_review # лише ті, що потребують перевірки
```

## Конфігурація (змінні оточення)

| Змінна | За замовчуванням | Опис |
|---|---|---|
| `INVOICEFLOW_HOME` | `~/.invoiceflow` | базова тека (inbox, store, БД) |
| `OLLAMA_URL` | `http://localhost:11434` | адреса Ollama |
| `INVOICEFLOW_MODEL` | `qwen2.5:14b` | модель витягування |
| `INVOICEFLOW_OCR_LANG` | `eng` | мова Tesseract |
| `INVOICEFLOW_TEXT_THRESHOLD` | `100` | мін. символів/сторінку, щоб вважати PDF цифровим (інакше OCR) |
| `INVOICEFLOW_MAX_ATTEMPTS` | `3` | спроби обробки job |

## Структура проєкту

```
invoiceflow/        пакет
  config.py         налаштування
  crypto.py         AES-256-GCM + ключ із Keychain
  db.py models.py   SQLite (WAL) + ORM
  schema.py         pydantic-схема інвойсу + JSON-схема для Ollama
  store.py queue.py зберігання + черга
  ingest.py reader.py extractor.py validator.py worker.py
  cli.py            watch / work / list
tests/              pytest (20 тестів)
docs/superpowers/   дизайн-документ + план впровадження
```

## Тести

```bash
source .venv/bin/activate
pytest            # 20 passed
```
Юніт-тести мокають Ollama та Tesseract, тож проходять без них; повний наскрізний прогін потребує запущеного Ollama з моделлю.

## Дорожня карта

- [x] **Фаза 1** — конвеєр ingest→store + CLI (поточна)
- [ ] **Фаза 2** — Review UI (FastAPI + PDF.js): оригінал ↔ поля, підсвітка низької впевненості, редагування, approve, audit; веб-завантаження
- [ ] **Фаза 3** — email-приймач (IMAP) + `Exporter` (CSV/JSON → ERP/API)
