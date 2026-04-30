"""Workflow HTTP guards + state machine shortcuts."""

from fastapi.testclient import TestClient

from friday_api.main import app
from friday_workflow.engine import WorkflowEngine, WorkflowState


def test_templates_requires_user_header() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/workflows/templates")
    assert res.status_code == 401


def test_list_workflows_requires_user() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/workflows")
    assert res.status_code == 401


def test_create_workflow_requires_user() -> None:
    client = TestClient(app)
    res = client.post("/api/v1/workflows", json={"template": "daily_briefing"})
    assert res.status_code == 401


def test_engine_running_to_cancelled() -> None:
    eng = WorkflowEngine()
    assert eng.can_transition(WorkflowState.RUNNING, WorkflowState.CANCELLED)
