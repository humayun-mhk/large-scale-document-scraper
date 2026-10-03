import argparse

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Document
from app.tasks.download import download_document


def main(limit: int):
    with SessionLocal() as db:
        docs = db.scalars(
            select(Document)
            .where(Document.status == "PENDING")
            .order_by(Document.id)
            .limit(limit)
        ).all()

        if not docs:
            print("No PENDING documents found.")
            return

        queued = 0

        for doc in docs:
            # Do not enqueue viewer-only links.
            if "splitscreen=true" in doc.source_url.lower():
                doc.status = "SKIPPED"
                doc.last_error = "UI-only SPLITSCREEN link"
                continue

            result = download_document.delay(doc.id)
            doc.status = "QUEUED"
            queued += 1
            print(f"Queued document {doc.id}: {result.id}")

        db.commit()

        print(f"\nQueued: {queued}")
        print("Run check_documents.py after the worker finishes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    main(args.limit)
