"""Registered tool metadata."""

from __future__ import annotations

from fastapi import APIRouter

from friday_tools import RegisteredTool
from friday_api.runtime import get_tool_gateway

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools() -> list[dict]:
    gateway = get_tool_gateway()
    tools: list[RegisteredTool] = gateway.registry.all_tools()
    return [t.model_dump() for t in tools]
