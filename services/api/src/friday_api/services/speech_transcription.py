"""Server-side speech-to-text via OpenAI Whisper-compatible API."""

from __future__ import annotations

import os

import httpx
import structlog

from friday_api.config import Settings, get_settings

log = structlog.get_logger("friday.api.speech")


class TranscriptionConfigError(RuntimeError):
    """Misconfiguration (e.g. missing API key outside test)."""


class TranscriptionHttpError(RuntimeError):
    """Upstream STT failure."""


async def transcribe_audio_bytes(
    data: bytes,
    *,
    filename: str = "clip.webm",
    content_type: str | None = None,
    settings: Settings | None = None,
) -> str:
    """POST audio to OpenAI-compatible `.../audio/transcriptions` and return plain text."""
    s = settings or get_settings()
    if len(data) > s.stt_max_upload_bytes:
        raise TranscriptionConfigError("audio_too_large")

    if os.environ.get("FRIDAY_PYTEST") == "1":
        # Deterministic path for tests; ignores placeholder keys often present in local `.env`.
        return "mock stt transcription for pytest"

    key = (s.openai_api_key or "").strip()
    if not key:
        raise TranscriptionConfigError("openai_api_key_required_for_stt")

    url = f"{s.openai_base_url.rstrip('/')}/audio/transcriptions"
    upload_name = filename or "audio.webm"
    mime = content_type or "application/octet-stream"

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (upload_name, data, mime)},
                data={"model": s.openai_whisper_model},
            )
    except httpx.RequestError as exc:
        log.warning("stt_request_error", detail=str(exc)[:500])
        raise TranscriptionHttpError("stt_upstream_unreachable") from exc

    if resp.status_code >= 400:
        detail = resp.text[:1200]
        log.warning("stt_http_error", status=resp.status_code, detail=detail)
        raise TranscriptionHttpError(f"stt_upstream_{resp.status_code}")

    payload = resp.json()
    text = str(payload.get("text", "")).strip()
    return text
