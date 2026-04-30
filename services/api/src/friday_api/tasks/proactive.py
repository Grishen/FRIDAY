"""Celery task: periodic proactive notification fan-out."""

from __future__ import annotations

import structlog

from friday_api.celery_app import celery_app
from friday_api.services.proactive_dispatcher import run_proactive_tick_sync

logger = structlog.get_logger("friday.proactive")


@celery_app.task(name="friday.tasks.proactive_tick")
def proactive_tick_task() -> dict[str, object]:
    out = run_proactive_tick_sync()
    merged: dict[str, object] = {"status": "ok", **out}
    logger.info("proactive_tick_completed", **merged)
    return merged
