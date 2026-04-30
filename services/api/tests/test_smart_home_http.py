from fastapi.testclient import TestClient

from friday_api.main import app


def test_smart_home_requires_user_header() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/smart-home/devices").status_code == 401


def test_smart_home_get_device_requires_auth() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/smart-home/devices/living_room.main_light")
    assert res.status_code == 401


def test_smart_home_patch_requires_auth() -> None:
    client = TestClient(app)
    res = client.patch(
        "/api/v1/smart-home/devices/living_room.main_light",
        json={"state": {"on": False}},
    )
    assert res.status_code == 401
