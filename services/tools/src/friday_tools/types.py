from __future__ import annotations

from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolInvocation(BaseModel):
    tool_name: str
    input: Mapping[str, Any] = Field(default_factory=dict)
    user_id: UUID
    session_id: UUID | None = None
    trace_id: UUID | None = None
    workflow_id: UUID | None = None
    workflow_step_id: UUID | None = None


class ToolResult(BaseModel):
    ok: bool
    output: Mapping[str, Any] = Field(default_factory=dict)
    error: str | None = None
