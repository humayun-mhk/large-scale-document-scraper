from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Document


with SessionLocal() as db:
    total = db.scalar(select(func.count()).select_from(Document))
    print(f"Documents in Neon: {total}")

    rows = db.scalars(
        select(Document).order_by(Document.id.desc()).limit(20)
    ).all()

    for row in reversed(rows):
        print(
            f"{row.id} | {row.status:10} | "
            f"{row.document_type or '-':15} | "
            f"{(row.title or '')[:70]} | {row.source_url}"
        )
