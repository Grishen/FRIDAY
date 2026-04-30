"""Approval API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApprovalOut(BaseModel):
    id: uuid.UUID
    status: str
    tool_call_id: uuid.UUID | None
    tool_name: str | None = None
    reason: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_payload: dict | None

    model_config = {"from_attributes": True}


class ApprovalResolveBody(BaseModel):
    decision: str = Field(description="approve | deny")
    reason: str | None = None

    def is_approve(self) -> bool:
        return self.decision.lower() == "approve"


class ApprovalListResponse(BaseModel):
    items: list[ApprovalOut]
