"""Assemble planner context: transcript, tool catalog, memory hits."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_agent import ContextBundle, ContextBuilder
from friday_tools import ToolGateway

from friday_api.models import ChatSession, Message
from friday_api.services.memory_service import search_memories


async def recent_transcript(
    db: AsyncSession, *, session_id: uuid.UUID, limit: int = 24
) -> list[dict[str, str]]:
    """Chronological [{role, content}, ...] excluding huge meta."""

    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.scalars(stmt)).all())
    rows.reverse()
    out: list[dict[str, str]] = []
    for m in rows:
        out.append({"role": m.role, "content": (m.content or "")[:4000]})
    return out


async def memory_snippets_for_query(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[str]:
    if not query.strip():
        return []
    hits = await search_memories(
        db,
        user_id=user_id,
        query=query[:2000],
        memory_type=None,
        limit=limit,
    )
    return [h.memory.content[:1200] for h in hits]


async def load_turn_context_bundle(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session: ChatSession,
    user_text: str,
    tool_gateway: ToolGateway,
) -> ContextBundle:
    recent = await recent_transcript(db, session_id=session.id)
    snippets = await memory_snippets_for_query(db, user_id=user_id, query=user_text)
    available = [t.name for t in tool_gateway.registry.all_tools()]
    builder = ContextBuilder()
    return await builder.build(
        user_id=user_id,
        session_id=session.id,
        recent_messages=recent,
        extra={
            "memory_snippets": snippets,
            "available_tools": available,
            "now_iso": datetime.now(timezone.utc).isoformat(),
        },
    )
