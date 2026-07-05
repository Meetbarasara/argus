"""Celery application. Kept import-light (settings only) so the API can import it to
enqueue by name without pulling in the task implementations (or, later, the graph)."""

from __future__ import annotations

from celery import Celery

from argus.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "argus",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["argus.worker.tasks"],
)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)
