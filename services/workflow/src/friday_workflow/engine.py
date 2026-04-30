"""Workflow state machine — persisted state lives in API."""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkflowEngine:
    """Transitions and invariants; persistence via ``friday_api`` repositories."""

    def can_transition(self, current: WorkflowState, target: WorkflowState) -> bool:
        allowed = {
            WorkflowState.CREATED: {WorkflowState.PLANNING, WorkflowState.CANCELLED},
            WorkflowState.PLANNING: {
                WorkflowState.WAITING_FOR_TOOL,
                WorkflowState.WAITING_FOR_APPROVAL,
                WorkflowState.RUNNING,
                WorkflowState.FAILED,
            },
            WorkflowState.WAITING_FOR_TOOL: {WorkflowState.RUNNING, WorkflowState.FAILED},
            WorkflowState.WAITING_FOR_APPROVAL: {WorkflowState.RUNNING, WorkflowState.CANCELLED},
            WorkflowState.RUNNING: {
                WorkflowState.PAUSED,
                WorkflowState.COMPLETED,
                WorkflowState.FAILED,
                WorkflowState.CANCELLED,
            },
            WorkflowState.PAUSED: {WorkflowState.RUNNING, WorkflowState.CANCELLED},
            WorkflowState.FAILED: set(),
            WorkflowState.COMPLETED: set(),
            WorkflowState.CANCELLED: set(),
        }
        return target in allowed.get(current, set())
