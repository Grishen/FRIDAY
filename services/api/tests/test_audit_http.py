from fastapi.testclient import TestClient

from friday_api.main import app


def test_audit_requires_user() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/audit")
    assert res.status_code == 401
