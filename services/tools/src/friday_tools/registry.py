"""Tool registry — metadata and handler wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from friday_tools.types import RiskLevel


class RegisteredTool(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    risk_level: RiskLevel
    requires_approval: bool = False
    input_schema: Mapping[str, Any] = Field(default_factory=dict)
    output_schema: Mapping[str, Any] = Field(default_factory=dict)


ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, meta: RegisteredTool, handler: ToolHandler) -> None:
        self._tools[meta.name] = meta
        self._handlers[meta.name] = handler

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def handler(self, name: str) -> ToolHandler | None:
        return self._handlers.get(name)

    def all_tools(self) -> list[RegisteredTool]:
        return sorted(self._tools.values(), key=lambda t: t.name)
