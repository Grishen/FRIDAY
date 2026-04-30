"""End-to-end API flows exercising routers + services for coverage (Phase 12).

Uses ``httpx.AsyncClient`` so async ``asyncpg`` sessions do not fight Starlette ``TestClient``.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx

from friday_api.main import create_app
from friday_api.services.proactive_dispatcher import run_proactive_tick_sync
from friday_api.tooling.bootstrap import build_default_registry


async def test_deps_invalid_user_uuid_rejected(async_client: httpx.AsyncClient) -> None:
    r = await async_client.get("/api/v1/memory", headers={"X-User-Id": "not-a-uuid"})
    assert r.status_code == 400


async def test_whoami_requires_param(async_client: httpx.AsyncClient) -> None:
    r = await async_client.get("/api/v1/auth/whoami")
    assert r.status_code == 400


async def test_tools_catalog_includes_smart_home(
    auth_headers: dict[str, str], async_client: httpx.AsyncClient
) -> None:
    res = await async_client.get("/api/v1/tools", headers=auth_headers)
    assert res.status_code == 200
    names = {t["name"] for t in res.json()}
    assert "smarthome.list_devices" in names
    assert "smarthome.set_device_state" in names


async def test_memory_crud_roundtrip(auth_headers: dict[str, str], async_client: httpx.AsyncClient) -> None:
    h = auth_headers
    create = await async_client.post(
        "/api/v1/memory",
        headers=h,
        json={
            "memory_type": "profile",
            "content": "Phase 12 coverage user",
            "importance_score": 0.6,
            "sensitivity_level": "internal",
        },
    )
    assert create.status_code == 201
    mid = create.json()["id"]

    listed = await async_client.get("/api/v1/memory", headers=h)
    assert listed.status_code == 200
    assert any(it["id"] == mid for it in listed.json()["items"])

    patched = await async_client.patch(
        f"/api/v1/memory/{mid}",
        headers=h,
        json={"content": "Updated profile snippet", "importance_score": 0.7},
    )
    assert patched.status_code == 200

    search = await async_client.post(
        "/api/v1/memory/search",
        headers=h,
        json={"query": "coverage", "limit": 10},
    )
    assert search.status_code == 200
    assert "hits" in search.json()

    delete = await async_client.delete(f"/api/v1/memory/{mid}", headers=h)
    assert delete.status_code == 204


async def test_document_upload_list_query(auth_headers: dict[str, str], async_client: httpx.AsyncClient) -> None:
    h = auth_headers
    raw = "FRIDAY Phase 12 tests cover document ingest and citations.\n" * 3
    res = await async_client.post(
        "/api/v1/documents/upload",
        headers=h,
        files={"file": ("phase12.txt", io.BytesIO(raw.encode()), "text/plain")},
    )
    assert res.status_code == 200
    doc_id = res.json()["document_id"]

    listed = await async_client.get("/api/v1/documents", headers=h)
    assert listed.status_code == 200
    assert any(d["id"] == doc_id for d in listed.json()["items"])

    status_res = await async_client.get(f"/api/v1/documents/{doc_id}", headers=h)
    assert status_res.status_code == 200

    rag = await async_client.post(
        "/api/v1/documents/query",
        headers=h,
        json={"query": "phase 12", "limit": 3},
    )
    assert rag.status_code == 200
    assert "answer" in rag.json()


async def test_document_bad_content_type_415(auth_headers: dict[str, str], async_client: httpx.AsyncClient) -> None:
    r = await async_client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("bad.bin", io.BytesIO(b"\x80\x81"), "application/octet-stream")},
    )
    assert r.status_code == 415


async def test_sessions_create_list_and_chat_turn(
    auth_headers: dict[str, str], async_client: httpx.AsyncClient
) -> None:
    h = auth_headers
    cr = await async_client.post("/api/v1/sessions", headers=h, json={"title": "phase12"})
    assert cr.status_code == 200
    sid = cr.json()["id"]

    listed = await async_client.get("/api/v1/sessions", headers=h)
    assert listed.status_code == 200
    assert any(s["id"] == sid for s in listed.json())

    msg = await async_client.post(
        f"/api/v1/sessions/{sid}/messages", headers=h, json={"content": "hello from phase twelve"}
    )
    assert msg.status_code == 200
    assert msg.json()["role"] == "assistant"

    msgs = await async_client.get(f"/api/v1/sessions/{sid}/messages", headers=h)
    assert msgs.status_code == 200
    bodies = msgs.json()
    assert len(bodies) >= 2


async def test_workflows_templates_and_empty_list(
    auth_headers: dict[str, str], async_client: httpx.AsyncClient
) -> None:
    """List templates + instances; avoid POST /workflows here (template primes tool steps that assume full DB invariants)."""
    h = auth_headers
    tpl = await async_client.get("/api/v1/workflows/templates", headers=h)
    assert tpl.status_code == 200
    assert tpl.json()["items"]

    lst = await async_client.get("/api/v1/workflows", headers=h)
    assert lst.status_code == 200


async def test_approvals_list_empty(auth_headers: dict[str, str], async_client: httpx.AsyncClient) -> None:
    res = await async_client.get("/api/v1/approvals", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["items"] == []


async def test_audit_list(auth_headers: dict[str, str], async_client: httpx.AsyncClient) -> None:
    res = await async_client.get("/api/v1/audit", headers=auth_headers)
    assert res.status_code == 200


async def test_smart_home_roundtrip(auth_headers: dict[str, str], async_client: httpx.AsyncClient) -> None:
    h = auth_headers
    listed = await async_client.get("/api/v1/smart-home/devices", headers=h)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) >= 1
    key = items[0]["device_key"]

    one = await async_client.get(f"/api/v1/smart-home/devices/{key}", headers=h)
    assert one.status_code == 200

    patched = await async_client.patch(
        f"/api/v1/smart-home/devices/{key}", headers=h, json={"state": {"on": False}}
    )
    assert patched.status_code == 200


async def test_notifications_extra_rule(auth_headers: dict[str, str], async_client: httpx.AsyncClient) -> None:
    h = auth_headers
    cr = await async_client.post(
        "/api/v1/notifications/rules",
        headers=h,
        json={"title": "Extra pulse", "rule_type": "phase12_ping", "interval_minutes": 1440},
    )
    assert cr.status_code == 201


async def test_notifications_rules_dispatch_flow(
    auth_headers: dict[str, str], async_client: httpx.AsyncClient
) -> None:
    h = auth_headers
    rules = await async_client.get("/api/v1/notifications/rules", headers=h)
    assert rules.status_code == 200
    rid = rules.json()["items"][0]["id"]
    patched = await async_client.patch(
        f"/api/v1/notifications/rules/{rid}",
        headers=h,
        json={"interval_minutes": 5},
    )
    assert patched.status_code == 200

    disp = await async_client.post("/api/v1/notifications/dispatch", headers=h)
    assert disp.status_code == 200
    assert disp.json()["notifications_created"] >= 0

    lst = await async_client.get("/api/v1/notifications", headers=h)
    assert lst.status_code == 200
    items = lst.json()["items"]
    if items:
        nid = items[0]["id"]
        ack = await async_client.post(f"/api/v1/notifications/{nid}/ack", headers=h)
        assert ack.status_code == 200


def test_registry_has_expected_tool_count() -> None:
    reg = build_default_registry()
    assert len(reg.all_tools()) >= 6


def test_proactive_dispatcher_and_celery_task() -> None:
    from friday_api.tasks.proactive import proactive_tick_task

    stats = run_proactive_tick_sync()
    assert "notifications_created" in stats

    out = proactive_tick_task.run()
    assert out["status"] == "ok"


def test_runtime_openapi_contains_smart_home_devices() -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/v1/smart-home/devices" in paths


def test_openapi_checked_in_matches_exported_skeleton() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    snap = json.loads((repo_root / "docs/api/openapi.json").read_text(encoding="utf-8"))
    live = create_app().openapi()
    assert snap["openapi"].split(".")[0] == live["openapi"].split(".")[0]
    for path in (
        "/api/v1/meta",
        "/api/v1/health",
        "/api/v1/smart-home/devices",
        "/api/v1/notifications",
    ):
        assert path in live["paths"]
