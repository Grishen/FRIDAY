"""SQL-backed audit recorder."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from friday_audit import AuditEventInput, AuditRecorder
from friday_api.models import AuditLog


class SqlAuditRecorder(AuditRecorder):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: AuditEventInput) -> uuid.UUID:
        row = AuditLog(
            user_id=event.user_id,
            category=event.category.value,
            action=event.action,
            trace_id=event.trace_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            severity=event.severity,
            payload=dict(event.payload),
        )
        self._session.add(row)
        await self._session.flush()
        return row.id


class SyncSqlAuditRecorder:
    """Append audit rows from Celery / sync code paths."""

    def append(self, session: Session, event: AuditEventInput) -> uuid.UUID:
        row = AuditLog(
            user_id=event.user_id,
            category=event.category.value,
            action=event.action,
            trace_id=event.trace_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            severity=event.severity,
            payload=dict(event.payload),
        )
        session.add(row)
        session.flush()
        return row.id


async def fetch_recent_audit(session: AsyncSession, user_id: uuid.UUID, limit: int = 50):
    result = await session.scalars(
        select(AuditLog)
        .where(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return list(result.all())
