from fastapi.testclient import TestClient

from friday_api.main import app


def test_notifications_requires_user() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/notifications")
    assert res.status_code == 401


def test_notification_rules_requires_user() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/notifications/rules")
    assert res.status_code == 401


def test_notification_dispatch_requires_user() -> None:
    client = TestClient(app)
    res = client.post("/api/v1/notifications/dispatch")
    assert res.status_code == 401
