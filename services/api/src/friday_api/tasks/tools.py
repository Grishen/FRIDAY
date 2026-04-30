"""Post-approval execution path — runs sandboxed handlers via ToolGateway."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from friday_audit import AuditCategory, AuditEventInput
from friday_tools import PolicyEngine, ToolGateway, ToolInvocation

from friday_api.celery_app import celery_app
from friday_api.db.sync_session import SyncSessionLocal
from friday_api.persistence.audit import SyncSqlAuditRecorder
from friday_api.models import Approval, ToolCall
from friday_api.tooling.bootstrap import build_default_registry

logger = logging.getLogger("friday.worker")


@celery_app.task(name="friday.tasks.execute_tool_call")
def execute_approved_tool_call(tool_call_id: str) -> dict:
    """Execute a handler after human approval."""
    tc_uuid = UUID(tool_call_id)
    registry = build_default_registry()
    gateway = ToolGateway(registry, PolicyEngine())

    with SyncSessionLocal() as session:
        tc = session.get(ToolCall, tc_uuid)
        if not tc:
            return {"error": "tool_call_not_found", "tool_call_id": tool_call_id}
        if tc.status != "queued":
            return {"status": "skipped_non_queued", "current": tc.status}

        approval = session.scalar(select(Approval).where(Approval.tool_call_id == tc.id))
        if not approval or approval.status != "approved":
            tc.status = "failed"
            session.commit()
            return {"error": "approval_invalid", "approval_status": getattr(approval, "status", None)}

        tc.status = "running"
        session.commit()

    inv = ToolInvocation(
        tool_name=tc.tool_name,
        input=dict(tc.input_payload or {}),
        user_id=tc.user_id,
        session_id=tc.session_id,
        trace_id=tc.trace_id,
    )

    try:
        result = asyncio.run(gateway.execute_approved(inv))
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool_execution_failed", extra={"tool_call_id": tool_call_id})
        _persist_failure(tc_uuid, str(exc))
        return {"ok": False, "error": str(exc)}

    with SyncSessionLocal() as session:
        tc2 = session.get(ToolCall, tc_uuid)
        if tc2:
            tc2.completed_at = datetime.now(timezone.utc)
            tc2.output_payload = result.model_dump()
            tc2.status = "completed" if result.ok else "failed"
            audit = SyncSqlAuditRecorder()
            pl: dict = {
                "tool": tc2.tool_name,
                "ok": result.ok,
            }
            if result.ok and result.output is not None:
                pl["output"] = dict(result.output)
            elif not result.ok:
                pl["error"] = result.error
            audit.append(
                session,
                AuditEventInput(
                    user_id=tc2.user_id,
                    category=AuditCategory.TOOL_CALL,
                    action="tool.execution_completed" if result.ok else "tool.execution_failed",
                    trace_id=tc2.trace_id,
                    resource_type="tool_call",
                    resource_id=str(tc2.id),
                    payload=pl,
                ),
            )
            session.commit()
    return {"ok": result.ok, "tool_call_id": tool_call_id, "detail": result.model_dump()}


def _persist_failure(tool_call_uuid: UUID, message: str) -> None:
    with SyncSessionLocal() as session:
        row = session.get(ToolCall, tool_call_uuid)
        if row:
            row.completed_at = datetime.now(timezone.utc)
            row.status = "failed"
            row.output_payload = {"error": message}
            session.commit()
