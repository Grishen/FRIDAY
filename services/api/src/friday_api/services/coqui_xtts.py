"""Coqui XTTS synthesis: discontinued cloud Studio API or local HTTP sidecar."""

from __future__ import annotations

import re

import httpx
import structlog

from friday_api.config import Settings, get_settings

log = structlog.get_logger("friday.api.coqui")


class CoquiMisconfigured(RuntimeError):
    """Missing token, voice_id, or local URL."""


class CoquiSynthesisFailed(RuntimeError):
    """Upstream non-200 or empty body."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


_WS = re.compile(r"\s+")


def chunk_xtts_english(text: str, *, max_chars: int = 240) -> list[str]:
    """Split prose into XTTS-safe chunks (hosted limit ~250 chars for EN)."""
    normalized = _WS.sub(" ", text.strip())
    if not normalized:
        return []
    paragraphs = [p.strip() for p in normalized.split(". ") if p.strip()]
    if not paragraphs:
        return [normalized[:max_chars]]

    buckets: list[str] = []
    current = ""
    for p in paragraphs:
        piece = p if p.endswith(".") else f"{p}."
        if len(current) + len(piece) + (1 if current else 0) <= max_chars:
            current = f"{current} {piece}".strip()
        else:
            if current:
                buckets.extend(_burst_long_sentence(current, max_chars=max_chars))
            current = piece
    if current:
        buckets.extend(_burst_long_sentence(current, max_chars=max_chars))
    return [b for b in buckets if b]


def _burst_long_sentence(blob: str, *, max_chars: int) -> list[str]:
    if len(blob) <= max_chars:
        return [blob]
    bits: list[str] = []
    words = blob.split(" ")
    acc = ""
    for w in words:
        tentative = (acc + " " + w).strip() if acc else w
        if len(tentative) <= max_chars:
            acc = tentative
        else:
            if acc:
                bits.append(acc)
            acc = w
    if acc:
        bits.append(acc)
    return bits


def _normalize_backend(raw: str) -> str:
    b = (raw or "remote").strip().lower()
    if b in ("local", "local_http", "localhost"):
        return "local_http"
    return b


async def _synthesize_remote_studio_http(text: str, s: Settings) -> bytes:
    token = (s.coqui_api_token or "").strip()
    vid = (s.coqui_voice_id or "").strip()
    if not token or not vid:
        raise CoquiMisconfigured("coqui_api_token_and_voice_id_required_for_remote_backend")

    base = (s.coqui_api_base_url or "https://app.coqui.ai").rstrip("/")
    url = f"{base}/api/v2/samples/xtts"

    payload = {
        "voice_id": vid,
        "text": text.strip(),
        "language": (s.coqui_language or "en").strip(),
        "speed": float(s.coqui_tts_speed),
        "format": "wav",
    }

    headers = {"Authorization": f"Bearer {token}", "Accept": "audio/wav"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            log.warning("coqui_xtts_transport", detail=str(exc)[:480])
            raise CoquiSynthesisFailed(503, str(exc)) from exc

    if resp.status_code < 200 or resp.status_code >= 300:
        body = resp.text[:1600].replace("\n", " ").strip()
        log.warning("coqui_xtts_http", status=resp.status_code, body=body)
        raise CoquiSynthesisFailed(resp.status_code, body or "coqui_upstream_error")

    wav = resp.content
    if not wav:
        raise CoquiSynthesisFailed(resp.status_code, "empty_waveform")
    return wav


async def _synthesize_local_sidecar_http(text: str, s: Settings) -> bytes:
    base = (s.coqui_local_tts_url or "").strip().rstrip("/")
    if not base:
        raise CoquiMisconfigured("coqui_local_tts_url_required_for_local_http_backend")

    url = f"{base}/v1/synthesize"
    payload = {
        "text": text.strip(),
        "language": (s.coqui_language or "en").strip(),
        "speed": float(s.coqui_tts_speed),
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.post(url, json=payload, headers={"Accept": "audio/wav"})
        except httpx.RequestError as exc:
            log.warning("coqui_local_transport", detail=str(exc)[:480])
            raise CoquiSynthesisFailed(503, str(exc)) from exc

    if resp.status_code < 200 or resp.status_code >= 300:
        body = resp.text[:1600].replace("\n", " ").strip()
        log.warning("coqui_local_http", status=resp.status_code, body=body)
        raise CoquiSynthesisFailed(resp.status_code, body or "coqui_local_upstream_error")

    wav = resp.content
    if not wav:
        raise CoquiSynthesisFailed(resp.status_code, "empty_waveform")
    return wav


async def synthesize_single_xtts_clip(
    text: str,
    *,
    settings: Settings | None = None,
) -> bytes:
    s = settings or get_settings()
    backend = _normalize_backend(s.coqui_tts_backend)

    if backend == "local_http":
        return await _synthesize_local_sidecar_http(text, s)
    if backend == "remote":
        return await _synthesize_remote_studio_http(text, s)

    raise CoquiMisconfigured(f"coqui_tts_backend_unsupported:{backend!r}")
