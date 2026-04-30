"""Read-only audit trail for the authenticated user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.db.session import get_session
from friday_api.deps import get_current_user
from friday_api.models import User
from friday_api.persistence.audit import fetch_recent_audit
from friday_api.schemas.audit import AuditListResponse, AuditLogOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
async def list_audit_logs(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
) -> AuditListResponse:
    rows = await fetch_recent_audit(db, user_id=user.id, limit=limit)
    return AuditListResponse(items=[AuditLogOut.model_validate(r) for r in rows])
