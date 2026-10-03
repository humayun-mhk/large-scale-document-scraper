from app.celery_app import celery

@celery.task
def health_check():
    return {"status": "ok", "message": "Celery + Redis are working"}
