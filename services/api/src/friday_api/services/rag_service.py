"""Vector search over document chunks + mocked synthesis with citations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.models import Document, DocumentChunk
from friday_api.providers.embeddings import cosine_distance_to_display_score, get_embedding_provider
from friday_api.providers.mock import MockChatProvider


async def search_chunks(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    limit: int = 12,
) -> list[tuple[DocumentChunk, str, float]]:
    prov = get_embedding_provider()
    q_vec = (await prov.embed([query]))[0]

    dist_expr = DocumentChunk.embedding.cosine_distance(q_vec)
    stmt = (
        select(DocumentChunk, Document.title, dist_expr.label("vec_dist"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.user_id == user_id)
        .where(Document.user_id == user_id)
        .where(DocumentChunk.embedding.isnot(None))
        .where(Document.status == "ready")
        .order_by(dist_expr.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    out: list[tuple[DocumentChunk, str, float]] = []
    for chunk, title, dist in result.all():
        score = cosine_distance_to_display_score(float(dist))
        out.append((chunk, title, score))
    return out


async def answer_with_rag(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    limit: int = 8,
) -> dict[str, Any]:
    rows = await search_chunks(db, user_id=user_id, query=query, limit=limit)
    citations: list[dict[str, Any]] = []

    if not rows:
        return {
            "answer": "No grounded chunks found — upload `.txt` content via POST /documents/upload first.",
            "citations": [],
        }

    parts: list[str] = []
    for ch, title, score in rows:
        excerpt = ch.text[:500] + ("…" if len(ch.text) > 500 else "")
        parts.append(f"[Document: {title} · chunk #{ch.ordinal}] (relevance {(score * 100):.0f}%)\n{ch.text}")
        citations.append(
            {
                "document_id": ch.document_id,
                "document_title": title,
                "chunk_ordinal": ch.ordinal,
                "score": score,
                "excerpt": excerpt,
            }
        )

    bundle = "\n\n---\n\n".join(parts)
    llm = MockChatProvider()
    messages = [
        {
            "role": "system",
            "content": "Answer succinctly using only the excerpts. End with Sources: listing document titles used.",
        },
        {"role": "user", "content": f"Question: {query}\n\nEvidence:\n{bundle}"},
    ]
    answer = await llm.complete(messages=messages)

    return {"answer": answer, "citations": citations}
