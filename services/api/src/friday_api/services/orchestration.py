"""Turn-taking orchestration across agents and tools."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from friday_agent import IntentRouter, PlannerAgent, ResponseAgent
from friday_agent.agents_specialized import SecurityAgent
from friday_audit import AuditCategory, AuditEventInput
from friday_tools import ToolGateway, ToolInvocation

from friday_api.models import ChatSession, Message
from friday_api.config import get_settings
from friday_api.persistence.audit import SqlAuditRecorder
from friday_api.providers.factory import get_chat_provider
from friday_api.services.approval_store import persist_if_pending
from friday_api.services.turn_context import load_turn_context_bundle

OnPhase = Callable[[str, dict[str, Any]], Awaitable[None]]
OnLlmDelta = Callable[[str], Awaitable[None]]


def _phase_for_tool(tool_name: str) -> str:
    if tool_name.startswith("calendar."):
        return "checking_calendar"
    if tool_name.startswith("documents."):
        return "reading_documents"
    if tool_name.startswith("email."):
        return "checking_email"
    if tool_name.startswith("local."):
        return "executing"
    return "executing"


async def append_message(
    db: AsyncSession, *, session: ChatSession, role: str, content: str, meta: dict | None = None
) -> Message:
    msg = Message(session_id=session.id, role=role, content=content, meta=meta)
    db.add(msg)
    await db.flush()
    return msg


async def run_turn(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    session: ChatSession,
    user_text: str,
    tool_gateway: ToolGateway,
    trace_id: uuid.UUID | None = None,
    on_phase: OnPhase | None = None,
    on_llm_delta: OnLlmDelta | None = None,
) -> tuple[str, dict]:
    """Returns assistant plain text plus debug envelope."""
    router = IntentRouter()
    planner = PlannerAgent()
    responder = ResponseAgent()
    settings = get_settings()
    llm = get_chat_provider(settings)

    trace_id = trace_id or uuid.uuid4()

    async def _emit(phase: str, detail: dict[str, Any] | None = None) -> None:
        if on_phase:
            await on_phase(phase, detail or {})

    safe, flags = await SecurityAgent().screen(user_text)
    if not safe:
        await _emit("error", {"reason": "policy_screen", "flags": flags})
        return await responder.render(f"I cannot comply ({', '.join(flags)})."), {
            "trace_id": str(trace_id),
            "blocked": flags,
        }

    await _emit("thinking", {"step": "intent"})
    intent = await router.classify(user_text)
    await _emit("thinking", {"step": "intent", "kind": intent.value})
    bundle = await load_turn_context_bundle(
        db,
        user_id=user_id,
        session=session,
        user_text=user_text,
        tool_gateway=tool_gateway,
    )
    await _emit(
        "thinking",
        {"step": "context", "memory_snippets": len(bundle.memory_snippets), "turns": len(bundle.recent_messages)},
    )
    plan = await planner.plan(
        user_text,
        {
            "intent": intent.value,
            "available_tools": bundle.available_tools,
            "memory_snippets": bundle.memory_snippets,
        },
    )

    tool_results: list[dict] = []
    for tool_name in plan.required_tools[:4]:
        if tool_name == "email.send":
            inv_input: dict = {
                "to": "team@example.com",
                "subject": "(mock) queued send",
                "body": user_text,
            }
        elif "ask" in tool_name:
            inv_input = {"query": user_text}
        elif tool_name.startswith("local."):
            from friday_api.services.local_tool_inputs import local_tool_inputs

            inv_input = local_tool_inputs(tool_name, user_text)
        else:
            inv_input = {}
        inv = ToolInvocation(
            tool_name=tool_name,
            input=inv_input,
            user_id=user_id,
            session_id=session.id,
            trace_id=trace_id,
        )
        await _emit(_phase_for_tool(tool_name), {"tool": tool_name})
        status, envelope = await tool_gateway.propose(inv)
        if status == "blocked":
            await SqlAuditRecorder(db).append(
                AuditEventInput(
                    user_id=user_id,
                    category=AuditCategory.TOOL_CALL,
                    action="tool.policy_blocked",
                    trace_id=trace_id,
                    resource_type="tool_invocation",
                    resource_id=tool_name,
                    payload={"reasons": envelope.get("reasons", [])},
                )
            )
        await persist_if_pending(
            db,
            user_id=user_id,
            session_id=session.id,
            trace_id=trace_id,
            tool_name=tool_name,
            inv=inv,
            status=status,
            envelope=envelope,
        )
        tool_results.append({"tool": tool_name, "status": status, "envelope": envelope})
        if status == "pending_approval":
            # Commit before WS + REST clients can resolve; otherwise rows are invisible → 404 on /approvals/.../resolve.
            await db.commit()
            raw_aid = envelope.get("approval_id")
            await _emit(
                "waiting_approval",
                {"tool": tool_name, "approval_id": str(raw_aid) if raw_aid is not None else None},
            )

    await _emit("synthesizing_response", {"step": "llm"})
    synthesis_context = json.dumps(tool_results, indent=2)
    mem_hint = ""
    if bundle.memory_snippets:
        bullets = "\n".join(f"- {s[:600]}" for s in bundle.memory_snippets[:5])
        mem_hint = f"\n\nRelevant long-term memory (retrieved for this turn):\n{bullets}"
    augmented_messages = [
        {
            "role": "system",
            "content": (
                "You are FRIDAY — a brisk, trustworthy personal AI operating assistant (think advanced copilot voice). "
                "Summarize crisply using tool JSON and retrieved memory when helpful. Prefer short paragraphs you could speak aloud.\n"
                f"{mem_hint.strip()}"
            ),
        },
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": synthesis_context[:8000]},
    ]
    try:
        parts: list[str] = []
        astream_fn = getattr(llm, "astream", None)
        if settings.llm_streaming and callable(astream_fn):
            async for piece in astream_fn(messages=augmented_messages, temperature=0.2):
                if piece:
                    parts.append(piece)
                    if on_llm_delta:
                        await on_llm_delta(piece)
        else:
            text_blk = await llm.complete(messages=augmented_messages, temperature=0.2)
            parts.append(text_blk)
        drafted_raw = "".join(parts)
        if settings.llm_streaming and not callable(astream_fn) and on_llm_delta and drafted_raw:
            step = max(16, len(drafted_raw) // 32)
            for i in range(0, len(drafted_raw), step):
                await on_llm_delta(drafted_raw[i : i + step])
    except Exception as exc:  # noqa: BLE001
        await _emit("error", {"reason": "llm_failure", "detail": str(exc)[:1200]})
        drafted_raw = "I couldn't reach the language model. Check OPENAI_API_KEY / base URL / network."

    final_text = await responder.render(
        drafted_raw, mode="deep technical" if "code" in user_text.lower() else "quick"
    )
    return (
        final_text,
        {
            "trace_id": str(trace_id),
            "intent": intent.value,
            "plan": plan.model_dump(),
            "context_summary": {
                "recent_messages": len(bundle.recent_messages),
                "memory_snippets": len(bundle.memory_snippets),
                "tools_registered": bundle.available_tools,
            },
            "tools": tool_results,
        },
    )
