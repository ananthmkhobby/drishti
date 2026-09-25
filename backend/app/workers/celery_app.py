from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aci",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_always_eager=settings.celery_always_eager,
    task_eager_propagates=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
