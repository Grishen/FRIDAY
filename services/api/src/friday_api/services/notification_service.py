"""In-app notifications + proactive rules orchestration."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.models import Notification, ProactiveRule

DEFAULT_DIGEST_TITLE = "FRIDAY digest"
DEFAULT_RULE_TYPE = "daily_digest"


async def ensure_default_digest_rule(db: AsyncSession, *, user_id: uuid.UUID) -> ProactiveRule:
    stmt = (
        select(ProactiveRule)
        .where(ProactiveRule.user_id == user_id, ProactiveRule.rule_type == DEFAULT_RULE_TYPE)
        .limit(1)
    )
    row = await db.scalar(stmt)
    if row:
        return row
    rule = ProactiveRule(
        id=uuid.uuid4(),
        user_id=user_id,
        title=DEFAULT_DIGEST_TITLE,
        rule_type=DEFAULT_RULE_TYPE,
        interval_minutes=1440,
        enabled=True,
        last_fired_at=None,
    )
    db.add(rule)
    await db.flush()
    return rule


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    unacknowledged_only: bool,
    limit: int,
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())
    if unacknowledged_only:
        stmt = stmt.where(Notification.acknowledged.is_(False))
    stmt = stmt.limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().unique().all())


async def acknowledge(db: AsyncSession, *, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification | None:
    stmt = (
        select(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user_id)
        .limit(1)
    )
    row = await db.scalar(stmt)
    if not row:
        return None
    row.acknowledged = True
    await db.flush()
    return row


async def list_rules(db: AsyncSession, *, user_id: uuid.UUID) -> list[ProactiveRule]:
    await ensure_default_digest_rule(db, user_id=user_id)
    res = await db.execute(
        select(ProactiveRule).where(ProactiveRule.user_id == user_id).order_by(ProactiveRule.created_at.asc())
    )
    return list(res.scalars().unique().all())


async def patch_rule(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    rule_id: uuid.UUID,
    enabled: bool | None,
    interval_minutes: int | None,
) -> ProactiveRule | None:
    stmt = (
        select(ProactiveRule)
        .where(ProactiveRule.id == rule_id, ProactiveRule.user_id == user_id)
        .limit(1)
    )
    row = await db.scalar(stmt)
    if not row:
        return None
    if enabled is not None:
        row.enabled = enabled
    if interval_minutes is not None:
        row.interval_minutes = interval_minutes
    await db.flush()
    return row


async def create_rule(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str,
    rule_type: str,
    interval_minutes: int,
) -> ProactiveRule:
    rule = ProactiveRule(
        id=uuid.uuid4(),
        user_id=user_id,
        title=title,
        rule_type=rule_type,
        interval_minutes=interval_minutes,
        enabled=True,
        last_fired_at=None,
    )
    db.add(rule)
    await db.flush()
    return rule
