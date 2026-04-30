"""Smart home stub devices (Phase 11)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.db.session import get_session
from friday_api.deps import get_current_user
from friday_api.models import User
from friday_api.schemas.smart_home_http import (
    SmartHomeDeviceListResponse,
    SmartHomeDeviceOut,
    SmartHomeDevicePatch,
)
from friday_api.services import smart_home_service

router = APIRouter(prefix="/smart-home", tags=["smart-home"])


@router.get("/devices", response_model=SmartHomeDeviceListResponse)
async def list_devices(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SmartHomeDeviceListResponse:
    rows = await smart_home_service.list_devices(db, user_id=user.id)
    return SmartHomeDeviceListResponse(items=[SmartHomeDeviceOut.model_validate(r) for r in rows])


@router.get("/devices/{device_key}", response_model=SmartHomeDeviceOut)
async def get_device(
    device_key: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SmartHomeDeviceOut:
    row = await smart_home_service.get_device(db, user_id=user.id, device_key=device_key)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown device_key")
    return SmartHomeDeviceOut.model_validate(row)


@router.patch("/devices/{device_key}", response_model=SmartHomeDeviceOut)
async def patch_device(
    device_key: str,
    body: SmartHomeDevicePatch,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SmartHomeDeviceOut:
    row = await smart_home_service.patch_device_state(
        db, user_id=user.id, device_key=device_key, patch=body.state
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown device_key")
    await db.commit()
    return SmartHomeDeviceOut.model_validate(row)
