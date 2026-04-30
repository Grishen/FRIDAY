"""Create and list tenant documents plus chunk persistence."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.models import Document, DocumentChunk
from friday_api.providers.embeddings import get_embedding_provider
from friday_api.services.text_chunking import split_text_into_chunks


async def ingest_plaintext_bytes(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str,
    mime_type: str,
    raw: bytes,
) -> Document:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("only_utf8_text_supported") from exc

    chunks_txt = split_text_into_chunks(text)
    doc = Document(
        user_id=user_id,
        title=title,
        mime_type=mime_type,
        status="processing",
        meta={"chunks_planned": len(chunks_txt)},
    )
    db.add(doc)
    await db.flush()

    if not chunks_txt:
        doc.status = "ready"
        await db.flush()
        return doc

    prov = get_embedding_provider()
    vectors = await prov.embed(chunks_txt)
    for ord_i, (chunk_body, vec) in enumerate(zip(chunks_txt, vectors, strict=True)):
        db.add(
            DocumentChunk(
                document_id=doc.id,
                user_id=user_id,
                ordinal=ord_i,
                text=chunk_body,
                embedding=vec,
                meta=None,
            )
        )
    doc.status = "ready"
    await db.flush()
    return doc


async def list_documents(db: AsyncSession, *, user_id: uuid.UUID) -> list[tuple[Document, int]]:
    stmt = select(Document).where(Document.user_id == user_id).order_by(Document.created_at.desc())
    rows = list((await db.scalars(stmt)).all())
    out: list[tuple[Document, int]] = []
    for d in rows:
        n = await db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == d.id)
        )
        out.append((d, int(n or 0)))
    return out


async def get_document(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
) -> Document | None:
    row = await db.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    return row


async def document_chunk_count(db: AsyncSession, *, document_id: uuid.UUID) -> int:
    n = await db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id))
    return int(n or 0)
