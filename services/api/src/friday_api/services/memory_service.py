"""Persisted memory + embedding helpers."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.models import Memory
from friday_api.providers.embeddings import cosine_distance_to_display_score, get_embedding_provider
from friday_api.schemas.memory import MemoryCreate, MemoryOut, MemorySearchHit, MemoryUpdate


async def create_memory(db: AsyncSession, *, user_id: uuid.UUID, data: MemoryCreate) -> Memory:
    emb = None
    if data.embed_now:
        prov = get_embedding_provider()
        vecs = await prov.embed([data.content])
        emb = vecs[0]

    row = Memory(
        user_id=user_id,
        memory_type=data.memory_type,
        content=data.content,
        importance_score=data.importance_score,
        sensitivity_level=data.sensitivity_level,
        embedding=emb,
        expires_at=data.expires_at,
    )
    db.add(row)
    await db.flush()
    return row


async def update_memory(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
    data: MemoryUpdate,
) -> Memory | None:
    row = await db.scalar(select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
    if not row:
        return None
    if data.content is not None:
        row.content = data.content
        if data.reembed:
            row.embedding = (await get_embedding_provider().embed([data.content]))[0]
    if data.importance_score is not None:
        row.importance_score = data.importance_score
    if data.sensitivity_level is not None:
        row.sensitivity_level = data.sensitivity_level
    if data.expires_at is not None:
        row.expires_at = data.expires_at
    await db.flush()
    return row


async def delete_memory(db: AsyncSession, *, user_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
    res = await db.execute(delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
    await db.flush()
    return res.rowcount > 0  # type: ignore[attr-defined]


async def list_memories(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    memory_type: str | None = None,
    limit: int = 100,
) -> Sequence[Memory]:
    stmt = select(Memory).where(Memory.user_id == user_id).order_by(Memory.updated_at.desc()).limit(limit)
    if memory_type:
        stmt = stmt.where(Memory.memory_type == memory_type)
    res = await db.scalars(stmt)
    return res.all()


async def search_memories(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    memory_type: str | None,
    limit: int,
) -> list[MemorySearchHit]:
    """Rank with pgvector cosine distance in SQL (scales with DB indexes when added)."""

    prov = get_embedding_provider()
    q_vec = (await prov.embed([query]))[0]

    dist_expr = Memory.embedding.cosine_distance(q_vec)
    stmt = (
        select(Memory, dist_expr.label("vec_dist"))
        .where(Memory.user_id == user_id)
        .where(Memory.embedding.isnot(None))
        .order_by(dist_expr.asc())
        .limit(limit)
    )
    if memory_type:
        stmt = stmt.where(Memory.memory_type == memory_type)

    result = await db.execute(stmt)
    out: list[MemorySearchHit] = []
    for row in result.all():
        m = row[0]
        dist = row[1]
        score = cosine_distance_to_display_score(float(dist))
        out.append(MemorySearchHit(memory=MemoryOut.from_memory(m), score=score))
    return out
