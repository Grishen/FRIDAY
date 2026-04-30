"""WebSocket chat + presence updates."""

from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from friday_api.config import get_settings
from friday_api.db.session import SessionLocal
from friday_api.models import ChatSession
from friday_api.runtime import get_tool_gateway
from friday_api.services.orchestration import append_message, run_turn
from friday_api.services.speech_transcription import (
    TranscriptionConfigError,
    TranscriptionHttpError,
    transcribe_audio_bytes,
)

router = APIRouter(tags=["websocket"])


async def _send_status(ws: WebSocket, phase: str, detail: dict[str, Any] | None = None) -> None:
    await ws.send_text(
        json.dumps(
            {
                "type": "status",
                "phase": phase,
                "detail": detail or {},
                "trace_id": str(uuid.uuid4()),
            }
        )
    )


@router.websocket("/ws/v1/sessions/{session_id}")
async def session_socket(websocket: WebSocket, session_id: uuid.UUID) -> None:
    await websocket.accept()
    user_header = websocket.headers.get("x-user-id")
    query_user = websocket.query_params.get("user_id")
    raw_uid = user_header or query_user
    if not raw_uid:
        await websocket.close(code=4401)
        return
    try:
        user_uuid = uuid.UUID(raw_uid)
    except ValueError:
        await websocket.close(code=4400)
        return

    async with SessionLocal() as db:
        sess = await db.scalar(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_uuid)
        )
        if not sess:
            await websocket.close(code=4404)
            return

    settings = get_settings()
    hint_stt = "client_stt_web_speech_api"
    if settings.openai_api_key.strip():
        hint_stt = "multiplex_web_speech_or_server_whisper"

    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            msg_type = str(payload.get("type", ""))

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "trace_id": str(uuid.uuid4())}))
                continue

            if msg_type == "voice.session_start":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "voice.ready",
                            "hint": hint_stt,
                            "server_stt": bool(settings.openai_api_key.strip() or os.environ.get("FRIDAY_PYTEST") == "1"),
                            "locale": payload.get("locale"),
                            "max_audio_bytes": settings.stt_max_upload_bytes,
                        }
                    )
                )
                continue

            text_part: str | None = None
            if msg_type == "user_message":
                text_part = str(payload.get("text", ""))
            elif msg_type == "voice.audio":
                b64_data = payload.get("data")
                if not isinstance(b64_data, str) or not b64_data.strip():
                    await websocket.send_text(
                        json.dumps(
                            {"type": "error", "detail": "voice_audio_missing_data", "trace_id": str(uuid.uuid4())}
                        )
                    )
                    continue
                try:
                    audio_bytes = base64.b64decode(b64_data, validate=False)
                except Exception:
                    await websocket.send_text(
                        json.dumps(
                            {"type": "error", "detail": "voice_audio_invalid_base64", "trace_id": str(uuid.uuid4())}
                        )
                    )
                    continue
                if len(audio_bytes) > settings.stt_max_upload_bytes:
                    await websocket.send_text(
                        json.dumps({"type": "error", "detail": "voice_audio_too_large", "trace_id": str(uuid.uuid4())})
                    )
                    continue
                fname = str(payload.get("filename") or "clip.webm")
                mime = str(payload.get("mime") or payload.get("content_type") or "audio/webm")
                await _send_status(websocket, "listening", {"step": "stt"})
                try:
                    transcript = await transcribe_audio_bytes(
                        audio_bytes, filename=fname, content_type=mime, settings=settings
                    )
                except TranscriptionConfigError:
                    await websocket.send_text(
                        json.dumps({"type": "error", "detail": "stt_not_configured", "trace_id": str(uuid.uuid4())})
                    )
                    continue
                except TranscriptionHttpError:
                    await websocket.send_text(
                        json.dumps({"type": "error", "detail": "stt_upstream_error", "trace_id": str(uuid.uuid4())})
                    )
                    continue
                transcript = transcript.strip()
                if not transcript:
                    await websocket.send_text(
                        json.dumps({"type": "error", "detail": "empty_transcript", "trace_id": str(uuid.uuid4())})
                    )
                    continue
                text_part = transcript
            else:
                await websocket.send_text(
                    json.dumps(
                        {"type": "error", "detail": "unsupported_frame", "trace_id": str(uuid.uuid4())}
                    )
                )
                continue

            assert text_part is not None

            await _send_status(websocket, "thinking", {"step": "route"})
            tid = uuid.uuid4()

            async def on_phase(phase: str, detail: dict[str, Any]) -> None:
                await _send_status(websocket, phase, detail)

            async with SessionLocal() as db:
                sess2 = await db.scalar(
                    select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_uuid)
                )
                if not sess2:
                    await websocket.close(code=4404)
                    return
                user_msg = await append_message(db, session=sess2, role="user", content=text_part)
                await db.flush()
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "conversation.user",
                            "data": {
                                "id": str(user_msg.id),
                                "session_id": str(sess2.id),
                                "content": text_part,
                            },
                            "trace_id": str(tid),
                        }
                    )
                )
                gateway = get_tool_gateway()

                async def on_delta(fragment: str) -> None:
                    if not fragment:
                        return
                    await websocket.send_text(
                        json.dumps({"type": "assistant.delta", "data": {"text": fragment}})
                    )

                assistant_text, meta = await run_turn(
                    db=db,
                    user_id=user_uuid,
                    session=sess2,
                    user_text=text_part,
                    tool_gateway=gateway,
                    trace_id=tid,
                    on_phase=on_phase,
                    on_llm_delta=on_delta,
                )
                msg = await append_message(
                    db, session=sess2, role="assistant", content=assistant_text, meta=meta
                )
                await db.commit()
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "assistant.message",
                        "data": {
                            "id": str(msg.id),
                            "content": assistant_text,
                            "meta": meta,
                        },
                    }
                )
            )
            await _send_status(websocket, "done", {"step": "complete"})
    except WebSocketDisconnect:
        return
