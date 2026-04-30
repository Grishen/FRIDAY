"""Dev-only auth helpers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.db.session import get_session
from friday_api.models import User
from friday_api.schemas.chat import BootstrapRequest, BootstrapResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/bootstrap", response_model=BootstrapResponse)
async def bootstrap_user(
    body: BootstrapRequest,
    db: AsyncSession = Depends(get_session),
) -> BootstrapResponse:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing:
        return BootstrapResponse(user_id=existing.id)
    user = User(id=uuid.uuid4(), email=body.email, hashed_password=None)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return BootstrapResponse(user_id=user.id)


@router.get("/whoami")
async def whoami(user_id: str | None = None, db: AsyncSession = Depends(get_session)) -> dict:
    if not user_id:
        raise HTTPException(status_code=400, detail="pass ?user_id=")
    uid = uuid.UUID(user_id)
    user = await db.scalar(select(User).where(User.id == uid))
    if not user:
        raise HTTPException(status_code=404, detail="not found")
    return {"id": str(user.id), "email": user.email}
