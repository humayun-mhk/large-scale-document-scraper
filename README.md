# Large Document Scraper

A production-style Python pipeline for discovering, queueing, downloading, deduplicating, and recovering large public-document collection jobs.

The project was built against real CivicWeb government portals and focuses on the engineering problems that matter at scale: dynamic discovery, persistent job state, retries, rate limiting, duplicate detection, resumability, and organization-based storage.

## Architecture

```text
Public CivicWeb Portal
        │
        ├── Playwright
        │   Dynamic page inspection / rendered navigation
        │
        └── MeetingsService
            Historical meeting discovery
                    │
                    ▼
              PostgreSQL / Neon
          Persistent document metadata
                    │
                    ▼
               Celery + Redis
            Background job queue
                    │
                    ▼
              Redis Rate Limiter
                    │
                    ▼
                  HTTPX
              File downloader
                    │
                    ▼
           SHA-256 deduplication
                    │
                    ▼
      Organization / document-type folders
```

Playwright is used only where browser execution is required. Once document URLs are discovered, files are downloaded directly with HTTPX for lower overhead.

## Features

- Dynamic document discovery with Playwright
- Historical meeting discovery through CivicWeb's public MeetingsService
- PostgreSQL-backed job state and source tracking
- Celery workers with Redis broker
- Retry handling for timeouts, `429`, and retryable `5xx` responses
- Exponential backoff
- Redis-based global rate limiting
- SHA-256 content deduplication
- Unique `source_url` protection against duplicate discovery
- Crash recovery for stale jobs
- Organization and document-type based storage
- Safe restart without starting the crawl again

Document states:

```text
PENDING → QUEUED → DOWNLOADING → DOWNLOADED
                     │
                     ├── RETRYING → FAILED
                     ├── DUPLICATE
                     └── SKIPPED
```

## Project Structure

```text
large_document_scraper/
├── app/
│   ├── discovery/
│   ├── downloader/
│   ├── protection/
│   ├── tasks/
│   ├── celery_app.py
│   ├── config.py
│   ├── database.py
│   └── models.py
│
├── scripts/
│   ├── discover.py
│   ├── enqueue_downloads.py
│   ├── check_documents.py
│   ├── init_db.py
│   └── recover_stale_jobs.py
│
├── tests/
│   └── reliability/
│
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Setup

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Example configuration:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DATABASE?sslmode=require
REDIS_URL=redis://localhost:6379/0
DOWNLOAD_DIR=./data
```

Start Redis and initialize the database:

```powershell
docker compose up -d
python -m scripts.init_db
```

Start a Celery worker in a separate terminal:

```powershell
celery -A app.celery_app.celery worker --loglevel=info --pool=solo
```

## Discover Documents

Example CivicWeb discovery run:

```powershell
python -m scripts.discover `
  --host "https://schreiber.civicweb.net" `
  --organization "Township of Schreiber" `
  --from-date "2015-01-01" `
  --to-date "2026-12-31" `
  --target-docs 250
```

Queue pending documents:

```powershell
python -m scripts.enqueue_downloads --limit 100
```

Inspect database status:

```powershell
python -m scripts.check_documents
```

Recover stale jobs after an interrupted worker:

```powershell
python -m scripts.recover_stale_jobs --minutes 10
```

Downloaded files are stored under `DOWNLOAD_DIR`, for example:

```text
data/
├── town-of-three-hills/
│   ├── agenda/
│   └── agenda-package/
└── township-of-schreiber/
    ├── agenda/
    └── agenda-package/
```

## Reliability Testing

The reliability fixtures simulate:

- `429 Too Many Requests`
- temporary `503 Service Unavailable`
- permanent `500 Internal Server Error`
- duplicate file content

Run the local fixture server:

```powershell
python -m tests.reliability.reliability_test_server
```

Seed and queue the test jobs:

```powershell
python -m tests.reliability.seed_reliability_tests
python -m tests.reliability.enqueue_reliability_tests
```

Inspect the final results:

```powershell
python -m tests.reliability.check_reliability_tests
```

## Problems Encountered and Resolved

### Limited visible history
The portal initially exposed only a small set of recent meetings.

**Solution:** browser network inspection revealed:

```text
/Services/MeetingsService.svc/meetings
```

Using its date range parameters exposed hundreds of historical meeting records and stable meeting IDs.

### Temporary browser/DNS failures
Playwright occasionally returned `net::ERR_NAME_NOT_RESOLVED`.

**Solution:** navigation retries and backoff were added so transient failures do not terminate the crawl.

### Encoded meeting URLs
Some URLs contained JavaScript-escaped values such as `\u0026`.

**Solution:** URLs are normalized before navigation.

### Duplicate documents
Different URLs can return the same file.

**Solution:** every downloaded file is hashed with SHA-256. Matching content is marked `DUPLICATE` instead of being stored twice.

### Interrupted workers
A process can stop while a document is `QUEUED`, `DOWNLOADING`, or `RETRYING`.

**Solution:** stale-job recovery moves abandoned work back to `PENDING`, allowing processing to resume without restarting the full crawl.

### Rate limits and server failures
Real collection jobs must tolerate temporary `429` and `5xx` responses.

**Solution:** retryable responses use exponential backoff; permanent failures are recorded as `FAILED`.

## Validated Run

The local implementation was tested with real public documents:

```text
Total records: 645
Downloaded:    363
Pending:       273
Duplicate:       4
Failed:          2
Skipped:         3
```

The historical discovery pipeline also returned hundreds of published meetings and inserted hundreds of new document records without restarting or duplicating previously discovered URLs.

## Scaling

The local demo validates the same state model required for much larger jobs.

For a 500k–900k document deployment, the architecture can scale horizontally with:

```text
Multiple discovery workers
        ↓
Managed PostgreSQL
        ↓
Managed Redis
        ↓
Multiple Celery worker containers
        ↓
Global rate limiting
        ↓
S3-compatible object storage
```

The core guarantees remain the same: persistent state, resumability, retries, deduplication, provenance, and failure tracking.

## Responsible Scraping

The system does not attempt to bypass CAPTCHAs, authentication controls, access restrictions, or explicit blocks. Persistent `403`, challenge pages, or repeated `429` responses should trigger backoff, logging, or manual review.

## Stack

**Python · Playwright · HTTPX · Celery · Redis · PostgreSQL/Neon · SQLAlchemy · Docker**

---

This repository demonstrates a resumable document-ingestion system rather than a one-off scraper: discovery, orchestration, rate control, retry handling, deduplication, storage organization, and recovery are all part of the pipeline.
