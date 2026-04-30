from fastapi.testclient import TestClient

from friday_api.main import app


def test_memory_requires_user() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/memory")
    assert res.status_code == 401
