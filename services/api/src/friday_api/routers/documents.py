"""Document upload / list / status + explicit RAG query endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.db.session import get_session
from friday_api.deps import get_current_user
from friday_api.models import User
from friday_api.schemas.documents_http import (
    CitationOut,
    DocumentListResponse,
    DocumentOut,
    DocumentStatusResponse,
    RAGQueryBody,
    RAGQueryResponse,
    UploadResponse,
)
from friday_api.services import document_service, rag_service

router = APIRouter(prefix="/documents", tags=["documents"])


def _sanitize_title(upload: UploadFile, explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()[:512]
    name = upload.filename or "upload.txt"
    return name.split("/")[-1][:512] or "Untitled"


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> UploadResponse:
    raw = await file.read()
    if len(raw) > 2_500_000:
        raise HTTPException(status_code=413, detail="file too large (max ~2.5MB for dev)")
    mt = file.content_type or "text/plain"
    if mt != "application/octet-stream" and not mt.startswith("text/"):
        raise HTTPException(status_code=415, detail=f"unsupported content type: {mt}")

    ttl = _sanitize_title(file, title)
    try:
        doc = await document_service.ingest_plaintext_bytes(
            db,
            user_id=user.id,
            title=ttl,
            mime_type=mt,
            raw=raw,
        )
    except ValueError as e:
        if str(e) == "only_utf8_text_supported":
            raise HTTPException(
                status_code=415,
                detail="Only UTF-8 plain text uploads are supported in this dev slice.",
            ) from e
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()
    await db.refresh(doc)
    n = await document_service.document_chunk_count(db, document_id=doc.id)
    return UploadResponse(document_id=doc.id, status=doc.status, chunk_count=n)


@router.get("", response_model=DocumentListResponse)
async def list_my_documents(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> DocumentListResponse:
    pairs = await document_service.list_documents(db, user_id=user.id)
    items = [
        DocumentOut(
            id=d.id,
            user_id=d.user_id,
            title=d.title,
            mime_type=d.mime_type,
            status=d.status,
            chunk_count=n,
            created_at=d.created_at,
        )
        for d, n in pairs
    ]
    return DocumentListResponse(items=items)


@router.post("/query", response_model=RAGQueryResponse)
async def rag_query(
    body: RAGQueryBody,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RAGQueryResponse:
    raw = await rag_service.answer_with_rag(
        db,
        user_id=user.id,
        query=body.query.strip(),
        limit=body.limit,
    )
    cites = [CitationOut.model_validate(c) for c in raw["citations"]]
    return RAGQueryResponse(answer=raw["answer"], citations=cites)


@router.get("/{document_id}")
@router.get("/{document_id}/status")
async def document_detail(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> DocumentStatusResponse:
    row = await document_service.get_document(db, user_id=user.id, document_id=document_id)
    if not row:
        raise HTTPException(status_code=404, detail="document not found")
    n = await document_service.document_chunk_count(db, document_id=document_id)
    return DocumentStatusResponse(id=row.id, status=row.status, title=row.title, chunk_count=n)
