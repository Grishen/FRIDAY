"""Bridge browser WebRTC offers to OpenAI Realtime unified `/v1/realtime/calls` endpoint."""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

log = structlog.get_logger("friday.api.realtime")


def _realtime_calls_url(api_base_url: str) -> str:
    """Map `OPENAI_BASE_URL` (typically .../v1) to unified WebRTC `{origin}/v1/realtime/calls`."""
    u = api_base_url.rstrip("/")
    origin = u[: -len("/v1")] if u.endswith("/v1") else u
    return f"{origin}/v1/realtime/calls"


async def exchange_realtime_webrtc_sdp(
    *,
    sdp_offer: str,
    api_key: str,
    api_base_url: str,
    session_payload: dict[str, Any],
    timeout_s: float = 60.0,
) -> tuple[int, str]:
    """
    Post multipart form (`sdp`, `session` JSON string) per OpenAI unified WebRTC docs.
    Returns (http_status, body_text) — body is answer SDP when status is success.
    """
    url = _realtime_calls_url(api_base_url)
    session_blob = json.dumps(session_payload)

    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            resp = await client.post(
                url,
                headers=headers,
                files={
                    "sdp": ("offer.sdp", sdp_offer.encode("utf-8"), "application/sdp"),
                    "session": ("session.json", session_blob.encode("utf-8"), "application/json"),
                },
            )
        except httpx.RequestError as exc:
            log.warning("realtime_calls_request_error", detail=str(exc)[:400])
            return 503, ""

    return resp.status_code, resp.text
