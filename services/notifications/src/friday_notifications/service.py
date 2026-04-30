"""Fan-out to in-app (WebSocket), desktop, email, push (stubs)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NotificationPayload(BaseModel):
    user_id: UUID
    title: str
    body: str
    channel: str = "in_app"
    data: dict[str, Any] = {}


class NotificationDispatcher:
    async def send(self, payload: NotificationPayload) -> UUID:  # pragma: no cover
        raise NotImplementedError
