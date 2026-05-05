"""SSE chat streaming + server-side transcription."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_transcribe_pytest_stub(
    async_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday_api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    r_sess = await async_client.post("/api/v1/sessions", json={"title": "stt"}, headers=auth_headers)
    assert r_sess.status_code == 200
    sid = r_sess.json()["id"]

    files = {"file": ("clip.webm", b"bogus-audio", "audio/webm")}
    r = await async_client.post(f"/api/v1/sessions/{sid}/transcribe", files=files, headers=auth_headers)
    assert r.status_code == 200
    text = str(r.json().get("text", "")).lower()
    assert "mock" in text

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_message_stream_contains_sse_events(
    async_client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    r_sess = await async_client.post("/api/v1/sessions", json={"title": "sse"}, headers=auth_headers)
    sid = str(r_sess.json()["id"])
    resp = await async_client.post(
        f"/api/v1/sessions/{sid}/messages/stream",
        json={"content": "hello friday streaming"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.text
    assert "event: conversation.user" in body
    assert "event: assistant.message" in body
    assert "event: done" in body
    # Streaming deltas appear when the upstream LLM tokenizes successfully; deterministic pytest / bad keys can skip deltas.
