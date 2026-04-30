"""Tenant-scoped memory CRUD + vector search."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.db.session import get_session
from friday_api.deps import get_current_user
from friday_api.models import User
from friday_api.schemas.memory import (
    MemoryCreate,
    MemoryListResponse,
    MemoryOut,
    MemorySearchBody,
    MemorySearchResponse,
    MemoryUpdate,
)
from friday_api.services import memory_service

router = APIRouter(prefix="/memory", tags=["memory"])


def _wrap(m: object) -> MemoryOut:
    return MemoryOut.from_memory(m)


@router.get("", response_model=MemoryListResponse)
async def list_memory(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    memory_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> MemoryListResponse:
    rows = await memory_service.list_memories(db, user_id=user.id, memory_type=memory_type, limit=limit)
    return MemoryListResponse(items=[_wrap(r) for r in rows])


@router.post("", response_model=MemoryOut, status_code=201)
async def create_memory_route(
    body: MemoryCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MemoryOut:
    row = await memory_service.create_memory(db, user_id=user.id, data=body)
    await db.commit()
    await db.refresh(row)
    return _wrap(row)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory_route(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MemoryOut:
    row = await memory_service.update_memory(db, user_id=user.id, memory_id=memory_id, data=body)
    if not row:
        raise HTTPException(status_code=404, detail="memory not found")
    await db.commit()
    await db.refresh(row)
    return _wrap(row)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory_route(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    ok = await memory_service.delete_memory(db, user_id=user.id, memory_id=memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="memory not found")
    await db.commit()


@router.post("/search", response_model=MemorySearchResponse)
async def search_memory(
    body: MemorySearchBody,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MemorySearchResponse:
    hits = await memory_service.search_memories(
        db,
        user_id=user.id,
        query=body.query,
        memory_type=body.memory_type,
        limit=body.limit,
    )
    return MemorySearchResponse(hits=hits)
