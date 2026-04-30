from fastapi.testclient import TestClient

from friday_api.main import app


def test_meta_public() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/meta")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "friday-api"
    assert "version" in body
    assert body["urls"]["openapi_json"] == "/openapi.json"
    assert body["urls"]["swagger_ui"] == "/docs"
    obs = body["observability"]
    assert obs["tracing_enabled"] is False
    assert obs["exporter"] == "none"
    assert obs["service_name"]


def test_ready_returns_schema() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/ready")
    assert res.status_code in (200, 503)
    body = res.json()
    assert "database" in body
    assert "redis" in body
    assert "status" in body
