"""Append-only audit trail interface. Persisted via API/session layer."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from pydantic import BaseModel, Field


class AuditCategory(str, Enum):
    TOOL_CALL = "tool_call"
    APPROVAL = "approval"
    WORKFLOW = "workflow"
    MEMORY = "memory"
    SECURITY = "security"
    MODEL = "model"
    SESSION = "session"


class AuditEventInput(BaseModel):
    user_id: UUID
    category: AuditCategory
    action: str
    trace_id: UUID | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    payload: Mapping[str, Any] = Field(default_factory=dict)
    severity: str = "info"


class AuditRecorder:
    """Abstract audit sink — implemented by persistence adapter in ``friday_api``."""

    async def append(self, event: AuditEventInput) -> UUID:  # pragma: no cover - interface
        raise NotImplementedError
