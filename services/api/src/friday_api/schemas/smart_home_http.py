"""HTTP schemas for smart home stubs (Phase 11)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SmartHomeDeviceOut(BaseModel):
    device_key: str
    name: str
    room: str
    kind: str
    state: dict[str, Any]


class SmartHomeDeviceListResponse(BaseModel):
    items: list[SmartHomeDeviceOut]


class SmartHomeDevicePatch(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)
