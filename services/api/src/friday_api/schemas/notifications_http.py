"""HTTP schemas for notifications + proactive rules (Phase 10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: uuid.UUID
    channel: str
    title: str
    body: str
    payload: dict[str, Any] | None
    acknowledged: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    items: list[NotificationOut]


class ProactiveRuleOut(BaseModel):
    id: uuid.UUID
    title: str
    rule_type: str
    interval_minutes: int
    enabled: bool
    last_fired_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProactiveRuleListResponse(BaseModel):
    items: list[ProactiveRuleOut]


class ProactiveRuleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    rule_type: str = Field(default="digest", max_length=64)
    interval_minutes: int = Field(default=1440, ge=5, le=10080)


class ProactiveRulePatch(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)


class DispatchResponse(BaseModel):
    status: str
    notifications_created: int
    rules_evaluated: int
