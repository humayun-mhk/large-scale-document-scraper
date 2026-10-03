from sqlalchemy import select

from app.database import SessionLocal
from app.models import Document

with SessionLocal() as db:
    docs = db.scalars(
        select(Document)
        .where(Document.organization == "Reliability Test")
        .order_by(Document.id)
    ).all()

    for doc in docs:
        print(
            f"{doc.id} | {doc.status:11} | retries={doc.retry_count} | "
            f"{doc.title} | {doc.last_error or ''}"
        )
