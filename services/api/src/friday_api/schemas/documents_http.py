"""HTTP schemas for documents + RAG."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    mime_type: str | None
    status: str
    chunk_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    items: list[DocumentOut]


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    chunk_count: int


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    title: str
    chunk_count: int


class RAGQueryBody(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=32)


class CitationOut(BaseModel):
    document_id: uuid.UUID
    document_title: str
    chunk_ordinal: int
    score: float
    excerpt: str


class RAGQueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
