"""Shared dependencies."""

from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.db.session import get_session
from friday_api.models import User


async def get_current_user(
    db: AsyncSession = Depends(get_session),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> User:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-Id (dev auth)",
        )
    try:
        uid = uuid.UUID(x_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid X-User-Id") from e
    row = await db.scalar(select(User).where(User.id == uid))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row
