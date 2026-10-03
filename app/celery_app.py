from celery import Celery
from app.config import settings

celery = Celery(
    "document_scraper",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.health",
        "app.tasks.download",
    ],
)

celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)
