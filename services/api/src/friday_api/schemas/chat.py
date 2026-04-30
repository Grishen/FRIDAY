"""Pydantic API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    email: str = "user@example.com"


class BootstrapResponse(BaseModel):
    user_id: uuid.UUID


class SessionCreate(BaseModel):
    title: str | None = None


class SessionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    meta: dict | None = None

    model_config = {"from_attributes": True}


class TranscribeOut(BaseModel):
    text: str
