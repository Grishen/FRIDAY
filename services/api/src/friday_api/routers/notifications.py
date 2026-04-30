"""In-app notifications and proactive schedules (Phase 10)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.db.session import get_session
from friday_api.deps import get_current_user
from friday_api.models import User
from friday_api.schemas.notifications_http import (
    DispatchResponse,
    NotificationListResponse,
    NotificationOut,
    ProactiveRuleCreate,
    ProactiveRuleListResponse,
    ProactiveRuleOut,
    ProactiveRulePatch,
)
from friday_api.services import notification_service
from friday_api.services.proactive_dispatcher import run_proactive_tick_sync

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    unacked_only: bool = Query(False, alias="unacked_only"),
    limit: int = Query(50, ge=1, le=200),
) -> NotificationListResponse:
    rows = await notification_service.list_notifications(
        db, user_id=user.id, unacknowledged_only=unacked_only, limit=limit
    )
    return NotificationListResponse(items=[NotificationOut.model_validate(r) for r in rows])


@router.post("/{notification_id}/ack", response_model=NotificationOut)
async def ack_notification(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> NotificationOut:
    row = await notification_service.acknowledge(db, user_id=user.id, notification_id=notification_id)
    if not row:
        raise HTTPException(status_code=404, detail="notification not found")
    await db.commit()
    await db.refresh(row)
    return NotificationOut.model_validate(row)


@router.get("/rules", response_model=ProactiveRuleListResponse)
async def list_rules(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProactiveRuleListResponse:
    rows = await notification_service.list_rules(db, user_id=user.id)
    await db.commit()
    return ProactiveRuleListResponse(items=[ProactiveRuleOut.model_validate(r) for r in rows])


@router.post("/rules", response_model=ProactiveRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: ProactiveRuleCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProactiveRuleOut:
    row = await notification_service.create_rule(
        db,
        user_id=user.id,
        title=body.title,
        rule_type=body.rule_type,
        interval_minutes=body.interval_minutes,
    )
    await db.commit()
    await db.refresh(row)
    return ProactiveRuleOut.model_validate(row)


@router.patch("/rules/{rule_id}", response_model=ProactiveRuleOut)
async def patch_rule(
    rule_id: uuid.UUID,
    body: ProactiveRulePatch,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProactiveRuleOut:
    row = await notification_service.patch_rule(
        db,
        user_id=user.id,
        rule_id=rule_id,
        enabled=body.enabled,
        interval_minutes=body.interval_minutes,
    )
    if not row:
        raise HTTPException(status_code=404, detail="rule not found")
    await db.commit()
    await db.refresh(row)
    return ProactiveRuleOut.model_validate(row)


@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_notifications_now(user: User = Depends(get_current_user)) -> DispatchResponse:
    """Run the proactive tick immediately (typically also scheduled via Celery beat)."""
    _ = user.id  # require auth; dispatcher still checks per-rule ownership
    stats = await asyncio.to_thread(run_proactive_tick_sync)
    return DispatchResponse(
        status="ok",
        notifications_created=stats.get("notifications_created", 0),
        rules_evaluated=stats.get("rules_evaluated", 0),
    )
