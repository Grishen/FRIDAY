"""Workflow API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowStepOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    order: float
    detail: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowOut(BaseModel):
    id: uuid.UUID
    template: str
    state: str
    context: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    items: list[WorkflowOut]


class WorkflowCreateBody(BaseModel):
    template: str = Field(..., min_length=1, max_length=128, description="Template id, e.g. daily_briefing")


class WorkflowTemplateOut(BaseModel):
    id: str
    title: str
    description: str
    step_count: int


class WorkflowTemplateListResponse(BaseModel):
    items: list[WorkflowTemplateOut]
