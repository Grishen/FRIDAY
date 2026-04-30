"""Async engine and session factory."""

from __future__ import annotations

import os

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from friday_api.config import get_settings

settings = get_settings()

_engine_kw: dict[str, object] = {"echo": settings.environment == "development"}
if os.environ.get("FRIDAY_PYTEST"):
    _engine_kw["poolclass"] = NullPool

engine = create_async_engine(settings.database_url, **_engine_kw)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
