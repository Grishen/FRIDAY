"""Memory API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    memory_type: str = Field(min_length=3, max_length=32)
    content: str = Field(min_length=1)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    sensitivity_level: str = Field(default="internal", max_length=32)
    expires_at: datetime | None = None
    embed_now: bool = Field(
        default=True,
        description="Compute and store embedding immediately (mock embedding in dev).",
    )


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    importance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    sensitivity_level: str | None = Field(default=None, max_length=32)
    expires_at: datetime | None = None
    reembed: bool = Field(default=True, description="Regenerate embedding when content changes.")


class MemoryOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    memory_type: str
    content: str
    importance_score: float
    sensitivity_level: str
    has_embedding: bool
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_memory(cls, m: object) -> MemoryOut:
        emb = getattr(m, "embedding", None)
        return cls(
            id=m.id,
            user_id=m.user_id,
            memory_type=m.memory_type,
            content=m.content,
            importance_score=m.importance_score,
            sensitivity_level=m.sensitivity_level,
            has_embedding=emb is not None,
            created_at=m.created_at,
            updated_at=m.updated_at,
            expires_at=m.expires_at,
        )


class MemorySearchBody(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=15, ge=1, le=100)
    memory_type: str | None = None


class MemorySearchHit(BaseModel):
    memory: MemoryOut
    score: float = Field(description="Mapped UI score ~0..1 from pgvector cosine distance")


class MemorySearchResponse(BaseModel):
    hits: list[MemorySearchHit]


class MemoryListResponse(BaseModel):
    items: list[MemoryOut]
