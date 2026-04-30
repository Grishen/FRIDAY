"""Audit log API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: uuid.UUID
    category: str
    action: str
    trace_id: uuid.UUID | None
    resource_type: str | None
    resource_id: str | None
    severity: str
    payload: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditListResponse(BaseModel):
    items: list[AuditLogOut]
