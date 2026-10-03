import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from app.celery_app import celery
from app.config import settings
from app.database import SessionLocal
from app.models import Document
from app.downloader.storage import build_final_path, choose_extension
from app.protection.rate_limiter import RedisRateLimiter


RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
rate_limiter = RedisRateLimiter(max_requests=3, window_seconds=1)


@celery.task(
    bind=True,
    autoretry_for=(),
    acks_late=True,
    reject_on_worker_lost=True,
)
def download_document(self, document_id: int):
    with SessionLocal() as db:
        doc = db.get(Document, document_id)

        if not doc:
            return {"status": "missing", "id": document_id}

        if doc.status == "DOWNLOADED":
            return {"status": "already_downloaded", "id": document_id}

        if "splitscreen=true" in doc.source_url.lower():
            doc.status = "SKIPPED"
            doc.last_error = "UI-only SPLITSCREEN link"
            db.commit()
            return {"status": "skipped", "id": document_id}

        doc.status = "DOWNLOADING"
        doc.retry_count = self.request.retries
        doc.last_error = None
        db.commit()

        temp_dir = Path(settings.download_dir) / ".tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{document_id}.part"

        try:
            # Global across every Celery worker.
            rate_limiter.wait()

            timeout = httpx.Timeout(60.0, connect=20.0)

            with httpx.Client(
                follow_redirects=True,
                timeout=timeout,
                headers={
                    "User-Agent": "LargeDocumentScraperDemo/1.0",
                    "Accept": "*/*",
                },
            ) as client:
                with client.stream("GET", doc.source_url) as response:
                    doc.http_status = response.status_code
                    doc.final_url = str(response.url)
                    doc.content_type = response.headers.get("content-type")

                    if response.status_code in RETRYABLE_STATUS:
                        raise httpx.HTTPStatusError(
                            f"Retryable HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )

                    response.raise_for_status()

                    if "text/html" in (doc.content_type or "").lower():
                        doc.status = "FAILED"
                        doc.last_error = "Expected file but received HTML"
                        db.commit()
                        return {"status": "failed", "id": document_id}

                    sha256 = hashlib.sha256()

                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            if chunk:
                                sha256.update(chunk)
                                f.write(chunk)

            digest = sha256.hexdigest()

            duplicate = db.scalar(
                select(Document).where(
                    Document.id != doc.id,
                    Document.sha256 == digest,
                    Document.status == "DOWNLOADED",
                ).limit(1)
            )

            if duplicate:
                if temp_path.exists():
                    temp_path.unlink()

                doc.sha256 = digest
                doc.status = "DUPLICATE"
                doc.last_error = f"Duplicate of document {duplicate.id}"
                doc.downloaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()

                return {
                    "status": "duplicate",
                    "id": document_id,
                    "duplicate_of": duplicate.id,
                }

            extension = choose_extension(
                doc.content_type,
                doc.final_url or doc.source_url,
            )

            final_path = build_final_path(
                settings.download_dir,
                doc.organization,
                doc.document_type or "document",
                doc.id,
                extension,
            )

            os.replace(temp_path, final_path)

            doc.sha256 = digest
            doc.file_path = str(final_path)
            doc.status = "DOWNLOADED"
            doc.downloaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
            doc.last_error = None
            db.commit()

            return {
                "status": "downloaded",
                "id": document_id,
                "file": str(final_path),
                "sha256": digest,
            }

        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            if temp_path.exists():
                temp_path.unlink()

            doc.retry_count = self.request.retries + 1
            doc.last_error = str(exc)[:2000]

            if self.request.retries < 4:
                doc.status = "RETRYING"
                db.commit()

                countdown = 5 * (3 ** self.request.retries)
                raise self.retry(exc=exc, countdown=countdown, max_retries=4)

            doc.status = "FAILED"
            db.commit()

            return {"status": "failed", "id": document_id, "error": str(exc)}

        except Exception as exc:
            if temp_path.exists():
                temp_path.unlink()

            doc.status = "FAILED"
            doc.last_error = str(exc)[:2000]
            db.commit()
            raise
