from fastapi.testclient import TestClient

from friday_api.main import app


def test_list_approvals_requires_user_header() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/approvals")
    assert res.status_code == 401


def test_celery_task_registered() -> None:
    from friday_api.celery_app import celery_app

    assert "friday.tasks.execute_tool_call" in celery_app.tasks
