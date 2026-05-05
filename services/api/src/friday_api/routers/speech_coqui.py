"""Speech: Coqui Studio XTTS (server-held token) + phrase wake/STT shim."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from friday_api.config import get_settings
from friday_api.deps import get_current_user
from friday_api.models import User
from friday_api.schemas.chat import CoquiTtsRequest, WakePhraseScanOut
from friday_api.services.coqui_xtts import CoquiMisconfigured, CoquiSynthesisFailed, synthesize_single_xtts_clip
from friday_api.services.speech_transcription import (
    TranscriptionConfigError,
    TranscriptionHttpError,
    transcribe_audio_bytes,
)

router = APIRouter(prefix="/speech", tags=["speech"])


def _phrase_matches(haystack_lower: str, phrase: str) -> bool:
    raw = phrase.strip().lower()
    if not raw:
        return False
    if any(c.isspace() for c in raw):
        return raw in haystack_lower
    return re.search(rf"(^|[^a-z0-9']){re.escape(raw)}([^a-z0-9']|$)", haystack_lower) is not None


def _wake_match(transcript: str, phrases_csv: str) -> bool:
    low = transcript.lower().strip()
    phrases = [p.strip() for p in phrases_csv.split(",") if p.strip()]
    if not phrases:
        phrases = ["friday"]
    return any(_phrase_matches(low, seg) for seg in phrases)


@router.post("/coqui/tts")
async def coqui_create_tts_clip(
    body: CoquiTtsRequest,
    _user: User = Depends(get_current_user),
):
    """Return a WAV clip for UI playback (server chunks long turns client-side)."""
    text = body.text.strip()
    if len(text) > 520:
        raise HTTPException(status_code=400, detail="text_fragment_too_long_chunk_client_side")

    try:
        wav = await synthesize_single_xtts_clip(text)
    except CoquiMisconfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except CoquiSynthesisFailed as e:
        raise HTTPException(status_code=502, detail=f"coqui_{e.status}:{e.detail[:1200]}") from e

    return StreamingResponse(
        iter([wav]),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/coqui/wake-scan", response_model=WakePhraseScanOut)
async def coqui_wake_scan(
    file: UploadFile = File(..., description="Short mic clip (~0.8–4s preferred)"),
    _user: User = Depends(get_current_user),
) -> WakePhraseScanOut:
    """
    Phrase-based wake: transcribe snippet, match configured phrases.

    STT currently reuses the OpenAI-compatible Whisper path (same as session transcribe). Swap the
    implementation if you stand up a dedicated Coqui ASR HTTP service.
    """
    settings = get_settings()
    max_bytes = settings.stt_max_upload_bytes
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="audio_too_large")

    ctype = file.content_type
    fname = (file.filename or "wake.webm").rsplit("/", maxsplit=1)[-1]

    try:
        transcript = await transcribe_audio_bytes(raw, filename=fname, content_type=ctype, settings=settings)
    except TranscriptionConfigError as e:
        raise HTTPException(status_code=503, detail="stt_not_configured_for_wake") from e
    except TranscriptionHttpError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    if not transcript:
        raise HTTPException(status_code=422, detail="empty_transcript")

    triggered = _wake_match(transcript, settings.friday_wake_phrases_csv)
    return WakePhraseScanOut(text=transcript, triggered=triggered)
