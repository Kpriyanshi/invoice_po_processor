# Invoice and PO Processing

FastAPI service that ingests invoice emails from Gmail (via Google Pub/Sub), classifies them, scans attachments for malware, extracts structured fields with **GPT-4 Vision OCR**, validates vendor/buyer **GSTIN** via API, stores results in **Postgres** (and JSON), and routes failures to a structured **exception queue** for manual review.

## Pipeline

```text
Gmail → Pub/Sub webhook
  → classify (keyword confidence)
  → MIME check + ClamAV scan
  → save PDF to data/invoices/
  → GPT-4 Vision OCR (background)
  → JSON (data/extracted/) + Postgres (invoices / invoice_line_items)
  → GSTIN API validation (vendor required; buyer if present)
  → on failure → exception case (case_id, category, root_cause)
```

## Features

| Area | What it does |
|------|----------------|
| **Ingest** | Gmail history + Pub/Sub `/webhook` |
| **Classify** | Subject/body/attachment keyword scoring |
| **Security** | MIME allow-list + ClamAV (port 3310) |
| **OCR** | GPT-4o vision via `ocr_module` (EasyOCR removed) |
| **Storage** | Dual-write: `data/extracted/*.json` + Postgres |
| **GSTIN** | Live check via [gstincheck.co.in](https://gstincheck.co.in/) |
| **Exceptions** | Structured cases in `data/exception_queue.json` |

## Requirements

- Python 3.11+
- Docker Desktop (ClamAV + Postgres)
- Google Cloud project with Gmail API + Pub/Sub
- OpenAI API key (OCR)
- Optional: GSTIN API key from gstincheck

## Quick start (local)

### 1. Clone and virtualenv

```powershell
cd InvoiceandPOprocessing
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Environment

```powershell
copy .env.example .env
```

Fill in at least:

- `OCR_OPENAI_API_KEY`
- `GSTIN_API_KEY` (if GSTIN validation enabled)
- `DATABASE_URL` (default matches docker-compose Postgres)

**Never commit `.env`.**

### 3. Start ClamAV + Postgres

```powershell
docker compose up -d clamav postgres
```

Wait until both are healthy (`docker compose ps`).

### 4. Run migrations

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

### 5. Gmail OAuth

Place `credentials.json` in the project root, then:

```powershell
.\venv\Scripts\python.exe scripts\auth.py
```

### 6. Run the API

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Expose `/webhook` publicly (e.g. ngrok) and point your Pub/Sub push subscription at it.

### Full stack with Docker

```powershell
docker compose up -d --build
```

App listens on `http://localhost:8000`. Inside Compose, ClamAV host is `clamav` and DB URL is set automatically.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `POST` | `/webhook` | Gmail Pub/Sub push |
| `GET` | `/queue` | All exception cases |
| `GET` | `/queue/pending` | Pending review only |
| `POST` | `/queue/{case_id}/review` | Body: `{"approved": true\|false}` |

Interactive docs: `http://127.0.0.1:8000/docs`

## Data layout

```text
data/
  invoices/           # Saved attachments
  extracted/          # OCR JSON (one file per PDF)
  exception_queue.json
  quarantine.json     # Per-file security rejects
  token.json          # Gmail OAuth token (gitignored)
```

### Postgres (`invoice_ocr`)

- **`invoices`** — header fields + `raw_extraction` (full OCR JSONB)
- **`invoice_line_items`** — line rows linked by `invoice_id`
- Unique on `source_file` (upsert on re-process)

```powershell
docker compose exec postgres psql -U invoice -d invoice_ocr -c "SELECT invoice_number, vendor_name, total_amount FROM invoices LIMIT 10;"
```

## Exception cases

Each new failure creates a case with:

- `case_id` (UUID)
- `timestamp`
- `category` — `classification` | `security` | `ocr` | `gstin` | `persistence` | `other`
- `root_cause` — e.g. `GSTIN_VENDOR_INVALID`, `SECURITY_ALL_ATTACHMENTS_REJECTED`
- `reason`, `signals`, `status` (`pending_review` / `approved` / `rejected`)

```powershell
curl http://127.0.0.1:8000/queue/pending
```

## Project structure

```text
app/
  api/v1/           # webhook, health, queue
  core/             # settings, keywords, logging
  db/               # SQLAlchemy models, session, repository
  services/
    ocr/            # vision_service (GPT OCR + dual-write + GSTIN hook)
    validation/     # GSTIN API client
    security/       # MIME + ClamAV
    classifier.py, processor.py, exception_*.py
ocr_module/         # GPT-4 Vision OCR package
alembic/            # DB migrations
scripts/            # auth, OCR config helpers
tests/
```

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests -q
```

## Useful commands

```powershell
# OCR config check
.\venv\Scripts\python.exe scripts\check_ocr_config.py

# Force re-OCR (delete existing JSON first)
Remove-Item ".\data\extracted\SomeFile.pdf.json" -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe -c "from app.services.ocr.vision_service import run_vision_ocr_job; print(run_vision_ocr_job(r'data\invoices\SomeFile.pdf'))"
```

## Notes

- Production OCR path is **GPT-4 Vision only** (`run_vision_ocr_job`).
- If `data/extracted/<file>.json` already exists, OCR is skipped (idempotent).
- Invalid GSTIN does not delete OCR/JSON/DB rows; it opens an exception case for review.
- Rotate any API keys that were pasted into chat or shared logs.
