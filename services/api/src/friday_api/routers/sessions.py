"""Session and messaging REST endpoints."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_api.config import get_settings
from friday_api.db.session import get_session
from friday_api.deps import get_current_user
from friday_api.models import ChatSession, Message, User
from friday_api.schemas.chat import MessageCreate, MessageOut, SessionCreate, SessionOut, TranscribeOut
from friday_api.runtime import get_tool_gateway
from friday_api.services.orchestration import append_message, run_turn
from friday_api.services.speech_transcription import (
    TranscriptionConfigError,
    TranscriptionHttpError,
    transcribe_audio_bytes,
)
from friday_api.services.realtime_openai import exchange_realtime_webrtc_sdp

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode("utf-8")


@router.post("", response_model=SessionOut)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChatSession:
    sess = ChatSession(user_id=user.id, title=body.title)
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ChatSession]:
    res = await db.scalars(select(ChatSession).where(ChatSession.user_id == user.id))
    return list(res.all())


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[Message]:
    sess = await db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id))
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    res = await db.scalars(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    )
    return list(res.all())


@router.post("/{session_id}/messages", response_model=MessageOut)
async def post_message(
    session_id: uuid.UUID,
    body: MessageCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Message:
    sess = await db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id))
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    await append_message(db, session=sess, role="user", content=body.content)
    gateway = get_tool_gateway()
    text, _meta = await run_turn(
        db=db,
        user_id=user.id,
        session=sess,
        user_text=body.content,
        tool_gateway=gateway,
    )
    assistant = await append_message(db, session=sess, role="assistant", content=text, meta=_meta)
    await db.commit()
    await db.refresh(assistant)
    return assistant


@router.post("/{session_id}/messages/stream")
async def post_message_stream(
    session_id: uuid.UUID,
    body: MessageCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    sess = await db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id))
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")

    async def gen() -> AsyncIterator[bytes]:
        user_msg = await append_message(db, session=sess, role="user", content=body.content)
        await db.commit()
        await db.refresh(user_msg)
        yield _sse(
            "conversation.user",
            {"id": str(user_msg.id), "session_id": str(sess.id), "content": body.content},
        )

        chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
        result_box: dict = {}

        gateway = get_tool_gateway()
        tid = uuid.uuid4()

        async def on_llm_delta(t: str) -> None:
            if not t:
                return
            await chunk_queue.put(t)

        async def runner() -> None:
            try:
                assistant_text, meta = await run_turn(
                    db=db,
                    user_id=user.id,
                    session=sess,
                    user_text=body.content,
                    tool_gateway=gateway,
                    trace_id=tid,
                    on_llm_delta=on_llm_delta,
                )
                msg_row = await append_message(
                    db, session=sess, role="assistant", content=assistant_text, meta=meta
                )
                await db.commit()
                await db.refresh(msg_row)
                result_box["text"] = assistant_text
                result_box["meta"] = meta
                result_box["msg"] = msg_row
            except Exception as exc:  # noqa: BLE001 — stream error envelope
                result_box["exc"] = exc
                await db.rollback()
            finally:
                await chunk_queue.put(None)

        task = asyncio.create_task(runner())
        while True:
            piece = await chunk_queue.get()
            if piece is None:
                break
            yield _sse("assistant.delta", {"text": piece})
        await task

        exc = result_box.get("exc")
        if exc is not None:
            yield _sse("error", {"detail": str(exc)[:1600]})
            yield _sse("done", {})
            return

        msg = result_box["msg"]
        assistant_text = str(result_box["text"])
        meta = result_box.get("meta") or {}
        yield _sse(
            "assistant.message",
            {
                "id": str(msg.id),
                "content": assistant_text,
                "meta": meta,
            },
        )
        yield _sse("done", {})

    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@router.post("/{session_id}/transcribe", response_model=TranscribeOut)
async def transcribe_session_audio(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    file: UploadFile = File(..., description="Short audio clip (e.g. webm/wav)"),
) -> TranscribeOut:
    sess = await db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id))
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")

    settings = get_settings()
    max_bytes = settings.stt_max_upload_bytes
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="audio_too_large")

    ctype = file.content_type
    fname = file.filename or "clip.webm"
    try:
        text = await transcribe_audio_bytes(raw, filename=fname, content_type=ctype, settings=settings)
    except TranscriptionConfigError as e:
        if str(e) == "audio_too_large":
            raise HTTPException(status_code=413, detail="audio_too_large") from e
        raise HTTPException(status_code=503, detail="stt_not_configured") from e
    except TranscriptionHttpError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    if not text:
        raise HTTPException(status_code=422, detail="empty_transcript")
    return TranscribeOut(text=text)


@router.post(
    "/{session_id}/realtime/webrtc",
    response_class=PlainTextResponse,
    summary="OpenAI Realtime WebRTC SDP exchange",
)
async def realtime_webrtc_sdp_offer(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Proxies SDP offer multipart to OpenAI **`POST /v1/realtime/calls`**.

    This path is intentionally **outside** orchestration/tool governance today —
    wire tools via Realtime server controls separately if needed.
    """
    sess = await db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id))
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")

    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="openai_api_key_required_for_realtime_webrtc")

    raw = await request.body()
    try:
        sdp_offer = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail="invalid sdp encoding") from e
    # Do not `.strip()` the whole SDP: trailing newlines are part of the wire format and
    # stripping breaks OpenAI's parser ("failed to unmarshal SDP: EOF").
    if sdp_offer.startswith("\ufeff"):
        sdp_offer = sdp_offer[1:]
    if not sdp_offer.strip():
        raise HTTPException(status_code=400, detail="empty sdp")

    session_payload: dict[str, object] = {
        "type": "realtime",
        "model": settings.openai_realtime_model,
        "audio": {
            "input": {"noise_reduction": {"type": "near_field"}},
            "output": {"voice": settings.openai_realtime_voice},
        },
        "instructions": settings.friday_realtime_instructions,
    }

    status, answer = await exchange_realtime_webrtc_sdp(
        sdp_offer=sdp_offer,
        api_key=api_key,
        api_base_url=settings.openai_base_url,
        session_payload=session_payload,
    )
    if status < 200 or status >= 300:
        snippet = answer[:2400].replace("\n", " ").strip()
        raise HTTPException(
            status_code=502,
            detail=f"upstream_realtime_{status}:{snippet}",
        )
    return PlainTextResponse(content=answer, media_type="application/sdp")
