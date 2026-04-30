"""Memory CRUD and search — persistence implemented in API layer."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from friday_memory.types import MemoryType, SensitivityLevel


class MemoryWrite(BaseModel):
    memory_type: MemoryType
    content: str
    importance_score: float = 0.5
    sensitivity_level: SensitivityLevel = SensitivityLevel.INTERNAL
    source_message_id: UUID | None = None
    expires_at: Any = None
    embedding: list[float] | None = None


class MemoryQuery(BaseModel):
    memory_type: MemoryType | None = None
    query_embedding: list[float] | None = None
    limit: int = 20


class MemoryService(Protocol):
    async def store(self, user_id: UUID, data: MemoryWrite) -> UUID: ...

    async def search(self, user_id: UUID, q: MemoryQuery) -> list[dict[str, Any]]: ...

    async def delete(self, user_id: UUID, memory_id: UUID) -> None: ...
