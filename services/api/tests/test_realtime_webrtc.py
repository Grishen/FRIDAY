"""OpenAI Realtime WebRTC SDP proxy."""

from __future__ import annotations

import uuid

import httpx
import pytest

from friday_api.config import get_settings


@pytest.mark.asyncio
async def test_realtime_webrtc_requires_api_key(
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    async_client: httpx.AsyncClient,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        r_sess = await async_client.post("/api/v1/sessions", json={"title": "rt"}, headers=auth_headers)
        assert r_sess.status_code == 200
        sid = r_sess.json()["id"]
        r = await async_client.post(
            f"/api/v1/sessions/{sid}/realtime/webrtc",
            headers={**auth_headers, "Content-Type": "application/sdp"},
            content="v=0\no=test",
        )
        assert r.status_code == 503
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_realtime_webrtc_proxied_when_upstream_ok(
    auth_headers: dict[str, str],
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday_api.routers import sessions as sessions_mod

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-realtime-gateway-only-placeholder")

    async def dummy_exchange(**_kw: object) -> tuple[int, str]:
        return 200, "v=0\ns=-\n"

    monkeypatch.setattr(sessions_mod, "exchange_realtime_webrtc_sdp", dummy_exchange)

    get_settings.cache_clear()

    try:
        r_sess = await async_client.post("/api/v1/sessions", json={"title": "rtp"}, headers=auth_headers)
        sid = uuid.UUID(str(r_sess.json()["id"]))
        hdrs = dict(auth_headers)
        hdrs["Content-Type"] = "application/sdp"
        resp = await async_client.post(
            f"/api/v1/sessions/{sid}/realtime/webrtc",
            headers=hdrs,
            content="v=0\r\noffer",
        )
        assert resp.status_code == 200
        assert resp.text.startswith("v=0")
    finally:
        get_settings.cache_clear()
