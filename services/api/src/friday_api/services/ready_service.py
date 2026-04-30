"""Dependency probes for readiness (Phase 9)."""

from __future__ import annotations

from typing import TypedDict

import redis.asyncio as redis_ai
from sqlalchemy import text

from friday_api.config import get_settings
from friday_api.db.session import SessionLocal


class ReadyResult(TypedDict):
    ok: bool
    error: str | None


async def probe_database() -> ReadyResult:
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "error": None}


async def probe_redis(url: str) -> ReadyResult:
    try:
        client = redis_ai.from_url(url, decode_responses=True)
        try:
            pong = await client.ping()
        finally:
            await client.aclose()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": bool(pong), "error": None if pong else "PING unexpected"}


async def readiness_bundle() -> tuple[ReadyResult, ReadyResult]:
    settings = get_settings()
    db = await probe_database()
    redis_r = await probe_redis(settings.redis_url)
    return db, redis_r
