"""Manage pending tool approvals and resume execution."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from friday_audit import AuditCategory, AuditEventInput

from friday_api.db.session import get_session
from friday_api.deps import get_current_user
from friday_api.models import Approval, ToolCall, User
from friday_api.persistence.audit import SqlAuditRecorder
from friday_api.runtime import get_tool_gateway
from friday_api.schemas.approvals import ApprovalListResponse, ApprovalOut, ApprovalResolveBody
from friday_api.services import workflow_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _enqueue_tool_execution(tool_call_id: str) -> None:
    from friday_api.tasks.tools import execute_approved_tool_call

    execute_approved_tool_call.delay(tool_call_id)


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    approval_status: str | None = Query(None, description="Filter by status, default pending"),
) -> ApprovalListResponse:
    filter_status = approval_status or "pending"
    tc = aliased(ToolCall)
    stmt = (
        select(Approval, tc.tool_name)
        .outerjoin(tc, tc.id == Approval.tool_call_id)
        .where(Approval.user_id == user.id, Approval.status == filter_status)
        .order_by(Approval.created_at.desc())
    )
    result = await db.execute(stmt)
    items: list[ApprovalOut] = []
    for appr, tool_name in result.all():
        base = ApprovalOut.model_validate(appr)
        items.append(base.model_copy(update={"tool_name": tool_name}))
    return ApprovalListResponse(items=items)


@router.post("/{approval_id}/resolve", response_model=ApprovalOut)
async def resolve_approval(
    approval_id: UUID,
    body: ApprovalResolveBody,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ApprovalOut:
    row = await db.scalar(select(Approval).where(Approval.id == approval_id))
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="approval not found")

    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="approval already resolved",
        )

    tool_call = await db.scalar(select(ToolCall).where(ToolCall.id == row.tool_call_id))
    if not tool_call:
        raise HTTPException(status_code=400, detail="tool call missing")

    lowered = body.decision.lower()
    if lowered not in {"approve", "deny"}:
        raise HTTPException(status_code=422, detail="decision must be approve or deny")

    actor = SqlAuditRecorder(db)
    now = datetime.now(timezone.utc)

    if lowered == "deny":
        row.status = "denied"
        row.resolved_at = now
        row.reason = body.reason
        row.resolved_payload = {"decision": "deny", "reason": body.reason}
        tool_call.status = "cancelled"
        tool_call.completed_at = now
        await actor.append(
            AuditEventInput(
                user_id=user.id,
                category=AuditCategory.APPROVAL,
                action="approval.denied",
                resource_type="approval",
                resource_id=str(row.id),
                payload={"tool_call_id": str(tool_call.id), "tool": tool_call.tool_name},
            )
        )
        await workflow_service.handle_tool_approval_resolution(
            db,
            tool_call=tool_call,
            decision="deny",
            tool_gateway=get_tool_gateway(),
        )
        await db.commit()
        await db.refresh(row)
        return ApprovalOut.model_validate(row).model_copy(update={"tool_name": tool_call.tool_name})

    row.status = "approved"
    row.resolved_at = now
    row.reason = body.reason
    row.resolved_payload = {"decision": "approve", "reason": body.reason}
    tool_call.status = "queued"

    await actor.append(
        AuditEventInput(
            user_id=user.id,
            category=AuditCategory.APPROVAL,
            action="approval.approved",
            resource_type="approval",
            resource_id=str(row.id),
            payload={"tool_call_id": str(tool_call.id), "tool": tool_call.tool_name},
        )
    )
    await workflow_service.handle_tool_approval_resolution(
        db,
        tool_call=tool_call,
        decision="approve",
        tool_gateway=get_tool_gateway(),
    )
    await db.commit()
    await db.refresh(row)

    _enqueue_tool_execution(str(tool_call.id))
    return ApprovalOut.model_validate(row).model_copy(update={"tool_name": tool_call.tool_name})
