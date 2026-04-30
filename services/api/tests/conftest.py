"""Shared fixtures."""

from __future__ import annotations

import os

os.environ.setdefault("FRIDAY_PYTEST", "1")

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from friday_api.main import app


@pytest.fixture(scope="session", autouse=True)
def _configure_tool_gateway_for_tests() -> None:
    """ASGI lifespan startup is not run by httpx.ASGITransport on this stack; mirror main.py wiring."""
    from friday_tools import PolicyEngine, ToolGateway

    from friday_api.runtime import configure_gateway
    from friday_api.tooling.bootstrap import build_default_registry

    reg = build_default_registry()
    configure_gateway(ToolGateway(reg, PolicyEngine()))


@pytest_asyncio.fixture(loop_scope="function")
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    """Async HTTP client against the ASGI app (avoids TestClient/asyncpg concurrency issues)."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(loop_scope="function")
async def auth_headers(async_client: httpx.AsyncClient) -> dict[str, str]:
    r = await async_client.post(
        "/api/v1/auth/bootstrap",
        json={"email": f"phase12-{uuid.uuid4().hex}@example.com"},
    )
    assert r.status_code == 200
    uid = r.json()["user_id"]
    return {"X-User-Id": uid}
