"""Assemble context bundle for planner and response agents."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContextBundle(BaseModel):
    user_id: UUID
    session_id: UUID
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    memory_snippets: list[str] = Field(default_factory=list)
    active_workflows: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    now_iso: str


class ContextBuilder:
    async def build(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        recent_messages: list[dict[str, Any]],
        extra: dict[str, Any] | None = None,
    ) -> ContextBundle:
        extra = extra or {}
        return ContextBundle(
            user_id=user_id,
            session_id=session_id,
            recent_messages=recent_messages,
            user_preferences=extra.get("user_preferences", {}),
            memory_snippets=extra.get("memory_snippets", []),
            active_workflows=extra.get("active_workflows", []),
            available_tools=extra.get("available_tools", []),
            now_iso=str(extra.get("now_iso", "")),
        )
