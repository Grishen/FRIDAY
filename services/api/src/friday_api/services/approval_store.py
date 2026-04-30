"""Persist tool calls + approvals when policy requires explicit approval."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from friday_tools.types import ToolInvocation
from friday_api.models import Approval, ToolCall


async def persist_if_pending(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID | None,
    trace_id: UUID | None,
    tool_name: str,
    inv: ToolInvocation,
    status: str,
    envelope: dict[str, Any],
) -> None:
    if status != "pending_approval":
        return
    raw_id = envelope.get("approval_id")
    if not raw_id:
        return
    approval_id = UUID(str(raw_id))
    tool_call_id = uuid.uuid4()
    tc = ToolCall(
        id=tool_call_id,
        user_id=user_id,
        session_id=session_id,
        tool_name=tool_name,
        input_payload=dict(inv.input),
        output_payload=None,
        status="awaiting_approval",
        trace_id=trace_id,
        workflow_id=inv.workflow_id,
        workflow_step_id=inv.workflow_step_id,
    )
    appr = Approval(
        id=approval_id,
        user_id=user_id,
        tool_call_id=tool_call_id,
        status="pending",
        reason=None,
        resolved_payload={"policy": envelope.get("decision")},
        resolved_at=None,
    )
    db.add(tc)
    db.add(appr)
    await db.flush()
