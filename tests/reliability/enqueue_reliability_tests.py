from sqlalchemy import select

from app.database import SessionLocal
from app.models import Document
from app.tasks.download import download_document

with SessionLocal() as db:
    docs = db.scalars(
        select(Document)
        .where(
            Document.organization == "Reliability Test",
            Document.status == "PENDING",
        )
        .order_by(Document.id)
    ).all()

    for doc in docs:
        result = download_document.delay(doc.id)
        doc.status = "QUEUED"
        print(f"Queued {doc.id}: {doc.title} -> {result.id}")

    db.commit()

print(f"Queued reliability jobs: {len(docs)}")
