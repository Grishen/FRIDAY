"""Static catalog for smart-home stubs (Phase 11).

Real hubs (Home Assistant, Matter) replace this seam later.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def clone_default_state(spec: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(spec["default_state"])


STUB_DEVICE_CATALOG: list[dict[str, Any]] = [
    {
        "device_key": "living_room.main_light",
        "name": "Living room overhead",
        "room": "Living room",
        "kind": "light",
        "default_state": {"on": True, "brightness": 55},
    },
    {
        "device_key": "bedroom.sensor_temp",
        "name": "Bedroom sensor",
        "room": "Bedroom",
        "kind": "sensor",
        "default_state": {"temperature_c": 21.5, "humidity_pct": 44},
    },
    {
        "device_key": "kitchen.switch_coffee",
        "name": "Coffee bar outlet",
        "room": "Kitchen",
        "kind": "switch",
        "default_state": {"on": False},
    },
    {
        "device_key": "entry.lock",
        "name": "Front door lock",
        "room": "Entry",
        "kind": "lock",
        "default_state": {"locked": True, "battery_pct": 82},
    },
]


def catalog_by_key() -> dict[str, dict[str, Any]]:
    return {d["device_key"]: d for d in STUB_DEVICE_CATALOG}
