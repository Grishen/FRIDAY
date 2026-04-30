"""Persisted smart home stub state + catalog merge (Phase 11)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.models import SmartHomeDeviceOverride
from friday_api.smart_home.catalog import STUB_DEVICE_CATALOG, catalog_by_key, clone_default_state
from friday_api.smart_home.state_merge import merge_state


async def _override_map(db: AsyncSession, user_id: uuid.UUID) -> dict[str, SmartHomeDeviceOverride]:
    res = await db.execute(
        select(SmartHomeDeviceOverride).where(SmartHomeDeviceOverride.user_id == user_id)
    )
    rows = list(res.scalars().unique().all())
    return {r.device_key: r for r in rows}


def _device_view(spec: dict[str, Any], override: SmartHomeDeviceOverride | None) -> dict[str, Any]:
    if override is not None:
        return dict(override.state)
    return clone_default_state(spec)


async def list_devices(db: AsyncSession, *, user_id: uuid.UUID) -> list[dict[str, Any]]:
    ov = await _override_map(db, user_id)
    out: list[dict[str, Any]] = []
    for spec in STUB_DEVICE_CATALOG:
        key = spec["device_key"]
        st = _device_view(spec, ov.get(key))
        out.append(
            {
                "device_key": key,
                "name": spec["name"],
                "room": spec["room"],
                "kind": spec["kind"],
                "state": st,
            }
        )
    return out


async def get_device(
    db: AsyncSession, *, user_id: uuid.UUID, device_key: str
) -> dict[str, Any] | None:
    cat = catalog_by_key()
    spec = cat.get(device_key)
    if spec is None:
        return None
    res = await db.execute(
        select(SmartHomeDeviceOverride).where(
            SmartHomeDeviceOverride.user_id == user_id,
            SmartHomeDeviceOverride.device_key == device_key,
        )
    )
    row = res.scalar_one_or_none()
    st = _device_view(spec, row)
    return {
        "device_key": device_key,
        "name": spec["name"],
        "room": spec["room"],
        "kind": spec["kind"],
        "state": st,
    }


async def patch_device_state(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    device_key: str,
    patch: Mapping[str, Any],
) -> dict[str, Any] | None:
    cat = catalog_by_key()
    spec = cat.get(device_key)
    if spec is None:
        return None
    current = clone_default_state(spec)
    res = await db.execute(
        select(SmartHomeDeviceOverride).where(
            SmartHomeDeviceOverride.user_id == user_id,
            SmartHomeDeviceOverride.device_key == device_key,
        )
    )
    row = res.scalar_one_or_none()
    if row is not None:
        current = dict(row.state)

    merged = merge_state(current, patch)
    if row is None:
        row = SmartHomeDeviceOverride(
            id=uuid.uuid4(),
            user_id=user_id,
            device_key=device_key,
            state=merged,
        )
        db.add(row)
    else:
        row.state = merged
    await db.flush()
    await db.refresh(row)
    return {
        "device_key": device_key,
        "name": spec["name"],
        "room": spec["room"],
        "kind": spec["kind"],
        "state": dict(row.state),
    }
