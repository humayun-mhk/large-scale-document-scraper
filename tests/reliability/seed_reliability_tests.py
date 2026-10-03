from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import Document

TESTS = [
    ("503 then success", "http://127.0.0.1:8765/retry503.pdf"),
    ("429 then success", "http://127.0.0.1:8765/retry429.pdf"),
    ("Permanent 500", "http://127.0.0.1:8765/always500.pdf"),
]

with SessionLocal() as db:
    for title, url in TESTS:
        stmt = (
            insert(Document)
            .values(
                organization="Reliability Test",
                title=title,
                document_type="TEST",
                source_url=url,
                status="PENDING",
            )
            .on_conflict_do_update(
                index_elements=["source_url"],
                set_={
                    "status": "PENDING",
                    "retry_count": 0,
                    "last_error": None,
                },
            )
        )
        db.execute(stmt)

    db.commit()

print("Seeded 3 reliability-test jobs.")
