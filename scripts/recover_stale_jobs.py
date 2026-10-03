import argparse
from datetime import datetime, timedelta
from datetime import datetime, timedelta, UTC
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Document


def main(minutes: int):
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)
    with SessionLocal() as db:
        docs = db.scalars(
            select(Document).where(
                Document.status.in_(["QUEUED", "DOWNLOADING", "RETRYING"]),
                Document.updated_at < cutoff,
            )
        ).all()

        for doc in docs:
            print(f"Recovering {doc.id}: {doc.status} -> PENDING")
            doc.status = "PENDING"
            doc.last_error = (
                f"Recovered automatically after being stale for > {minutes} minutes"
            )

        db.commit()

        print(f"\nRecovered jobs: {len(docs)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=10)
    args = parser.parse_args()
    main(args.minutes)
