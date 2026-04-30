"""Workflow templates and instance control (Phase 7)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.db.session import get_session
from friday_api.deps import get_current_user
from friday_api.models import User, Workflow
from friday_api.runtime import get_tool_gateway
from friday_api.schemas.workflows import (
    WorkflowCreateBody,
    WorkflowListResponse,
    WorkflowOut,
    WorkflowStepOut,
    WorkflowTemplateListResponse,
    WorkflowTemplateOut,
)
from friday_api.services import workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _workflow_to_out(wf: Workflow) -> WorkflowOut:
    steps = sorted(wf.steps, key=lambda s: (s.order, s.created_at))
    return WorkflowOut(
        id=wf.id,
        template=wf.template,
        state=wf.state,
        context=wf.context,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        steps=[WorkflowStepOut.model_validate(s) for s in steps],
    )


@router.get("/templates", response_model=WorkflowTemplateListResponse)
async def list_workflow_templates(_user: User = Depends(get_current_user)) -> WorkflowTemplateListResponse:
    raw = workflow_service.list_templates()
    return WorkflowTemplateListResponse(
        items=[
            WorkflowTemplateOut(
                id=r["id"],
                title=r["title"],
                description=r["description"],
                step_count=r["step_count"],
            )
            for r in raw
        ]
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows_route(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkflowListResponse:
    rows = await workflow_service.list_workflows(db, user_id=user.id)
    return WorkflowListResponse(items=[_workflow_to_out(w) for w in rows])


@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow_route(
    body: WorkflowCreateBody,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkflowOut:
    try:
        wf = await workflow_service.create_workflow(db, user_id=user.id, template_id=body.template)
        gw = get_tool_gateway()
        await workflow_service.prime_new_workflow(
            db, user_id=user.id, workflow_id=wf.id, tool_gateway=gw
        )
        await db.commit()
        fresh = await workflow_service.get_workflow(db, user_id=user.id, workflow_id=wf.id)
    except KeyError as e:
        raise HTTPException(status_code=400, detail="unknown template") from e
    if not fresh:
        raise HTTPException(status_code=500, detail="workflow missing after create")
    return _workflow_to_out(fresh)


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow_route(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkflowOut:
    wf = await workflow_service.get_workflow(db, user_id=user.id, workflow_id=workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    return _workflow_to_out(wf)


@router.post("/{workflow_id}/advance")
async def advance_workflow_route(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    wf = await workflow_service.get_workflow(db, user_id=user.id, workflow_id=workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    try:
        result = await workflow_service.advance_workflow(
            db, user_id=user.id, wf=wf, tool_gateway=get_tool_gateway()
        )
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    return result


@router.post("/{workflow_id}/pause", response_model=WorkflowOut)
async def pause_workflow_route(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkflowOut:
    wf = await workflow_service.get_workflow(db, user_id=user.id, workflow_id=workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    try:
        await workflow_service.pause_workflow(db, wf)
        await db.commit()
        await db.refresh(wf)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _workflow_to_out(wf)


@router.post("/{workflow_id}/resume", response_model=WorkflowOut)
async def resume_workflow_route(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkflowOut:
    wf = await workflow_service.get_workflow(db, user_id=user.id, workflow_id=workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    try:
        await workflow_service.resume_workflow(db, wf)
        await db.commit()
        await db.refresh(wf)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _workflow_to_out(wf)


@router.post("/{workflow_id}/cancel", response_model=WorkflowOut)
async def cancel_workflow_route(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkflowOut:
    wf = await workflow_service.get_workflow(db, user_id=user.id, workflow_id=workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    try:
        await workflow_service.cancel_workflow(db, wf)
        await db.commit()
        await db.refresh(wf)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _workflow_to_out(wf)
