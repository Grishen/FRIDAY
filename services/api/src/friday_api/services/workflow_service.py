"""Workflow templates, persistence, and execution (tool steps + approval pause)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from friday_tools import ToolGateway, ToolInvocation

from friday_api.models import ChatSession, ToolCall, Workflow, WorkflowStep
from friday_api.services.approval_store import persist_if_pending
from friday_workflow import WorkflowEngine, WorkflowState

logger = structlog.get_logger("friday.workflow")

_engine = WorkflowEngine()

StepSpec = dict[str, Any]

TEMPLATES: dict[str, dict[str, Any]] = {
    "daily_briefing": {
        "title": "Daily briefing",
        "description": "Calendar scan → digest → optional outbound email (approval-gated).",
        "steps": [
            {"key": "gather_context", "kind": "immediate", "label": "Gather calendar + memory context"},
            {"key": "draft_digest", "kind": "immediate", "label": "Draft briefing notes (mock)"},
            {
                "key": "send_team_ping",
                "kind": "tool",
                "tool": "email.send",
                "label": "Queue optional team email (high-risk → approval)",
            },
        ],
    },
    "meeting_prep": {
        "title": "Meeting prep",
        "description": "List meetings → pull related notes → optional follow-up email (approval-gated).",
        "steps": [
            {"key": "list_meetings", "kind": "immediate", "label": "List upcoming meetings (mock)"},
            {
                "key": "send_followup",
                "kind": "tool",
                "tool": "email.send",
                "label": "Queue follow-up email (approval)",
            },
        ],
    },
}


def list_templates() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tid, meta in TEMPLATES.items():
        steps = meta.get("steps", [])
        out.append(
            {
                "id": tid,
                "title": meta["title"],
                "description": meta["description"],
                "step_count": len(steps),
            }
        )
    return out


def _coerce_state(s: str) -> WorkflowState:
    try:
        return WorkflowState(s)
    except ValueError:
        return WorkflowState.CREATED


def _set_state(wf: Workflow, target: WorkflowState) -> None:
    cur = _coerce_state(wf.state)
    if not _engine.can_transition(cur, target):
        raise ValueError(f"invalid transition {cur.value} → {target.value}")
    wf.state = target.value


async def _pick_session(db: AsyncSession, user_id: uuid.UUID, title: str) -> ChatSession:
    sess = await db.scalar(
        select(ChatSession)
        .where(ChatSession.user_id == user_id, ChatSession.title == title)
        .order_by(ChatSession.updated_at.desc())
        .limit(1)
    )
    if sess:
        return sess
    row = ChatSession(user_id=user_id, title=title)
    db.add(row)
    await db.flush()
    return row


async def create_workflow(
    db: AsyncSession, *, user_id: uuid.UUID, template_id: str
) -> Workflow:
    if template_id not in TEMPLATES:
        raise KeyError("unknown template")
    meta = TEMPLATES[template_id]
    title = f"Workflow session · {meta['title']}"
    session = await _pick_session(db, user_id, title)
    wf = Workflow(
        user_id=user_id,
        template=template_id,
        state=WorkflowState.CREATED.value,
        context={"session_id": str(session.id)},
    )
    db.add(wf)
    await db.flush()

    steps_meta: list[StepSpec] = meta["steps"]
    for i, spec in enumerate(steps_meta):
        detail = dict(spec)
        st = WorkflowStep(
            workflow_id=wf.id,
            name=spec.get("label", spec.get("key", f"step_{i}")),
            status="pending" if i > 0 else "in_progress",
            order=float(i),
            detail=detail,
        )
        db.add(st)

    await db.flush()
    try:
        _set_state(wf, WorkflowState.PLANNING)
        _set_state(wf, WorkflowState.RUNNING)
    except ValueError:
        wf.state = WorkflowState.FAILED.value
        raise

    logger.info(
        "workflow_started",
        workflow_id=str(wf.id),
        template=template_id,
        user_id=str(user_id),
    )
    return wf


async def get_workflow(
    db: AsyncSession, *, user_id: uuid.UUID, workflow_id: uuid.UUID
) -> Workflow | None:
    wf = await db.scalar(
        select(Workflow)
        .options(selectinload(Workflow.steps))  # type: ignore[arg-type]
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
    )
    return wf


async def list_workflows(db: AsyncSession, *, user_id: uuid.UUID, limit: int = 50) -> list[Workflow]:
    stmt = (
        select(Workflow)
        .where(Workflow.user_id == user_id)
        .options(selectinload(Workflow.steps))  # type: ignore[arg-type]
        .order_by(Workflow.updated_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.scalars().unique().all())


def _sorted_steps(wf: Workflow) -> list[WorkflowStep]:
    steps = list(wf.steps)
    steps.sort(key=lambda s: (s.order, s.created_at.timestamp() if s.created_at else 0))
    return steps


def _current_step(wf: Workflow) -> WorkflowStep | None:
    for s in _sorted_steps(wf):
        if s.status == "in_progress":
            return s
    for s in _sorted_steps(wf):
        if s.status == "pending":
            return s
    return None


async def pause_workflow(db: AsyncSession, wf: Workflow) -> None:
    cur = _coerce_state(wf.state)
    if cur != WorkflowState.RUNNING:
        raise ValueError("can only pause from running")
    _set_state(wf, WorkflowState.PAUSED)


async def resume_workflow(db: AsyncSession, wf: Workflow) -> None:
    cur = _coerce_state(wf.state)
    if cur != WorkflowState.PAUSED:
        raise ValueError("can only resume from paused")
    _set_state(wf, WorkflowState.RUNNING)


async def cancel_workflow(db: AsyncSession, wf: Workflow) -> None:
    cur = _coerce_state(wf.state)
    if cur in (WorkflowState.COMPLETED, WorkflowState.CANCELLED, WorkflowState.FAILED):
        raise ValueError("already terminal")
    if cur == WorkflowState.PAUSED:
        _set_state(wf, WorkflowState.CANCELLED)
        return
    if cur == WorkflowState.WAITING_FOR_APPROVAL:
        _set_state(wf, WorkflowState.CANCELLED)
        return
    _set_state(wf, WorkflowState.CANCELLED)


async def _complete_step(db: AsyncSession, step: WorkflowStep, *, detail_patch: dict | None = None) -> None:
    step.status = "completed"
    if detail_patch:
        base = dict(step.detail or {})
        base.update(detail_patch)
        step.detail = base


async def _activate_next(db: AsyncSession, wf: Workflow, after: WorkflowStep) -> None:
    seen = False
    for s in _sorted_steps(wf):
        if seen and s.status == "pending":
            s.status = "in_progress"
            return
        if s.id == after.id:
            seen = True
    _set_state(wf, WorkflowState.COMPLETED)


async def advance_workflow(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    wf: Workflow,
    tool_gateway: ToolGateway,
    trace_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Run the current step: immediate steps complete; tool steps may enter waiting_for_approval."""
    state = _coerce_state(wf.state)
    if state == WorkflowState.PAUSED:
        raise ValueError("workflow is paused")
    if state == WorkflowState.WAITING_FOR_APPROVAL:
        raise ValueError("waiting for tool approval — resolve the approval first")
    if state in (WorkflowState.COMPLETED, WorkflowState.CANCELLED, WorkflowState.FAILED):
        raise ValueError("workflow is finished")

    step = _current_step(wf)
    if not step:
        _set_state(wf, WorkflowState.COMPLETED)
        return {"status": "already_complete"}

    detail = step.detail or {}
    kind = detail.get("kind")
    if kind == "immediate":
        await _complete_step(db, step, detail_patch={"completed_at": datetime.now(timezone.utc).isoformat()})
        await _activate_next(db, wf, step)
        return {"status": "step_completed", "step": step.name}

    if kind == "tool":
        tool_name = detail.get("tool")
        if not tool_name or not isinstance(tool_name, str):
            wf.state = WorkflowState.FAILED.value
            step.status = "failed"
            raise ValueError("invalid tool step")

        ctx = wf.context or {}
        sid_s = ctx.get("session_id")
        session_uuid = uuid.UUID(sid_s) if sid_s else None
        tid = trace_id or uuid.uuid4()
        inv = ToolInvocation(
            tool_name=tool_name,
            input={"to": "team@example.com", "subject": f"(workflow {wf.template}) step {step.name}", "body": "…"},
            user_id=user_id,
            session_id=session_uuid,
            trace_id=tid,
            workflow_id=wf.id,
            workflow_step_id=step.id,
        )
        status, envelope = await tool_gateway.propose(inv)
        if status == "blocked":
            step.status = "failed"
            wf.state = WorkflowState.FAILED.value
            return {"status": "blocked", "envelope": envelope}

        await persist_if_pending(
            db,
            user_id=user_id,
            session_id=session_uuid,
            trace_id=tid,
            tool_name=tool_name,
            inv=inv,
            status=status,
            envelope=envelope,
        )

        if status == "pending_approval":
            wf.state = WorkflowState.WAITING_FOR_APPROVAL.value
            raw_aid = envelope.get("approval_id") if envelope else None
            c = dict(wf.context or {})
            c["pending_approval_id"] = str(raw_aid) if raw_aid else None
            wf.context = c
            await db.flush()
            return {
                "status": "pending_approval",
                "approval_id": str(raw_aid) if raw_aid else None,
                "step_id": str(step.id),
            }

        if status == "completed":
            await _complete_step(db, step, detail_patch={"result": envelope})
            await _activate_next(db, wf, step)
            return {"status": "step_completed", "step": step.name}

        if status == "error":
            step.status = "failed"
            wf.state = WorkflowState.FAILED.value
            return {"status": "error", "envelope": envelope}

        step.status = "failed"
        wf.state = WorkflowState.FAILED.value
        return {"status": "unexpected_tool_status", "tool_status": status}

    step.status = "failed"
    wf.state = WorkflowState.FAILED.value
    raise ValueError(f"unknown step kind {kind}")


async def handle_tool_approval_resolution(
    db: AsyncSession,
    *,
    tool_call: ToolCall,
    decision: str,
    tool_gateway: ToolGateway,
) -> None:
    """Tie approvals router to workflows: unblock after resolve (same DB transaction before commit)."""
    if not tool_call.workflow_id or not tool_call.workflow_step_id:
        return

    wf = await get_workflow(db, user_id=tool_call.user_id, workflow_id=tool_call.workflow_id)
    if not wf:
        return
    step = await db.get(WorkflowStep, tool_call.workflow_step_id)
    if not step:
        return

    lowered = decision.lower()
    if lowered == "deny":
        step.status = "failed"
        try:
            _set_state(wf, WorkflowState.CANCELLED)
        except ValueError:
            wf.state = WorkflowState.CANCELLED.value
        logger.info("workflow_denied", workflow_id=str(wf.id), step_id=str(step.id))
        return

    if lowered != "approve":
        return

    try:
        cur = _coerce_state(wf.state)
        if cur == WorkflowState.WAITING_FOR_APPROVAL:
            _set_state(wf, WorkflowState.RUNNING)
    except ValueError:
        wf.state = WorkflowState.RUNNING.value

    await _complete_step(db, step, detail_patch={"approved": True})
    await _activate_next(db, wf, step)

    try:
        while _coerce_state(wf.state) == WorkflowState.RUNNING:
            nxt = _current_step(wf)
            if not nxt:
                break
            detail = nxt.detail or {}
            if detail.get("kind") != "immediate":
                break
            await _complete_step(
                db, nxt, detail_patch={"completed_at": datetime.now(timezone.utc).isoformat()}
            )
            await _activate_next(db, wf, nxt)
    except ValueError as e:
        logger.warning("workflow_chain_immediate_failed", error=str(e))

    wf = await get_workflow(db, user_id=tool_call.user_id, workflow_id=tool_call.workflow_id)
    if wf and _coerce_state(wf.state) == WorkflowState.RUNNING:
        nxt = _current_step(wf)
        if nxt and (nxt.detail or {}).get("kind") == "tool":
            await advance_workflow(db, user_id=wf.user_id, wf=wf, tool_gateway=tool_gateway)


async def prime_new_workflow(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    workflow_id: uuid.UUID,
    tool_gateway: ToolGateway,
    max_iterations: int = 48,
) -> Workflow | None:
    """Run immediate steps until the first tool invocation (often leaves workflow waiting_for_approval)."""
    for _ in range(max_iterations):
        wf = await get_workflow(db, user_id=user_id, workflow_id=workflow_id)
        if not wf:
            return None
        st = _coerce_state(wf.state)
        if st not in {WorkflowState.RUNNING, WorkflowState.WAITING_FOR_APPROVAL}:
            return wf
        if st == WorkflowState.WAITING_FOR_APPROVAL:
            return wf
        step = _current_step(wf)
        if not step:
            return wf
        kind = (step.detail or {}).get("kind")
        if kind == "tool":
            await advance_workflow(db, user_id=user_id, wf=wf, tool_gateway=tool_gateway)
            return await get_workflow(db, user_id=user_id, workflow_id=workflow_id)
        await advance_workflow(db, user_id=user_id, wf=wf, tool_gateway=tool_gateway)

    logger.warning("workflow_prime_iterations_exceeded", workflow_id=str(workflow_id))
    return await get_workflow(db, user_id=user_id, workflow_id=workflow_id)
