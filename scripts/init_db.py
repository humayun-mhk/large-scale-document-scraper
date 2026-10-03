from app.database import Base, engine
import app.models  # noqa

Base.metadata.create_all(engine)
print("Database tables created successfully.")
