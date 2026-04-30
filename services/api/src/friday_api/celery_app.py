"""Celery application wired to Redis (broker + optional result backend)."""

from __future__ import annotations

from datetime import timedelta

from celery import Celery

from friday_api.config import get_settings

settings = get_settings()

celery_app = Celery(
    "friday",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "proactive-notification-tick": {
            "task": "friday.tasks.proactive_tick",
            "schedule": timedelta(minutes=5),
        },
    },
)

import friday_api.tasks.proactive  # noqa: E402,F401 - registers Celery tasks via decorators
import friday_api.tasks.tools  # noqa: E402,F401 - registers Celery tasks via decorators
