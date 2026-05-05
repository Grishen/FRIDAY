"""Coqui XTTS proxy + phrase-wake shim."""

from __future__ import annotations

import pytest

import httpx


@pytest.mark.asyncio
async def test_coqui_wake_scan_mock_stt_no_trigger(async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    files = {"file": ("wake.webm", b"bogus", "audio/webm")}
    r = await async_client.post("/api/v1/speech/coqui/wake-scan", files=files, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "text" in body
    assert body.get("triggered") is False


@pytest.mark.asyncio
async def test_coqui_wake_scan_monkeypatch_triggers(
    async_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday_api.routers import speech_coqui

    async def fake_transcribe(_data: bytes, **_kw: object) -> str:
        return "hey buddy friday do this thing"

    monkeypatch.setattr(speech_coqui, "transcribe_audio_bytes", fake_transcribe)
    files = {"file": ("wake.webm", b"bogus", "audio/webm")}
    r = await async_client.post("/api/v1/speech/coqui/wake-scan", files=files, headers=auth_headers)
    assert r.status_code == 200
    assert r.json().get("triggered") is True


@pytest.mark.asyncio
async def test_coqui_tts_misconfigured_503(
    async_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday_api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("COQUI_TTS_BACKEND", "remote")
    monkeypatch.setenv("COQUI_API_TOKEN", "")
    monkeypatch.setenv("COQUI_VOICE_ID", "")
    try:
        r = await async_client.post(
            "/api/v1/speech/coqui/tts",
            json={"text": "hello"},
            headers=auth_headers,
        )
        assert r.status_code == 503
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_coqui_tts_ok_monkeypatch(
    async_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday_api.config import get_settings
    from friday_api.routers import speech_coqui

    async def fake_synth(_text: str, **_kw: object) -> bytes:
        return b"\x00wav"

    monkeypatch.setenv("COQUI_API_TOKEN", "dummy")
    monkeypatch.setenv("COQUI_VOICE_ID", "vid")
    monkeypatch.setenv("COQUI_TTS_BACKEND", "remote")
    monkeypatch.setattr(speech_coqui, "synthesize_single_xtts_clip", fake_synth)

    get_settings.cache_clear()
    try:
        r = await async_client.post(
            "/api/v1/speech/coqui/tts",
            json={"text": "hello"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("audio/wav")
        assert bytes(r.content) == b"\x00wav"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_coqui_tts_text_too_long_400(async_client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    r = await async_client.post(
        "/api/v1/speech/coqui/tts",
        json={"text": "x" * 521},
        headers=auth_headers,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_coqui_wake_scan_empty_transcript_422(
    async_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday_api.routers import speech_coqui

    async def empty_transcribe(_data: bytes, **_kw: object) -> str:
        return ""

    monkeypatch.setattr(speech_coqui, "transcribe_audio_bytes", empty_transcribe)
    files = {"file": ("wake.webm", b"z", "audio/webm")}
    r = await async_client.post("/api/v1/speech/coqui/wake-scan", files=files, headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_coqui_wake_scan_stt_upstream_502(
    async_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday_api.routers import speech_coqui
    from friday_api.services.speech_transcription import TranscriptionHttpError

    async def bad_transcribe(_data: bytes, **_kw: object) -> str:
        raise TranscriptionHttpError("stt_upstream_418")

    monkeypatch.setattr(speech_coqui, "transcribe_audio_bytes", bad_transcribe)
    files = {"file": ("wake.webm", b"z", "audio/webm")}
    r = await async_client.post("/api/v1/speech/coqui/wake-scan", files=files, headers=auth_headers)
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_coqui_tts_local_http_misconfigured_503(
    async_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday_api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("COQUI_TTS_BACKEND", "local_http")
    monkeypatch.setenv("COQUI_LOCAL_TTS_URL", "")
    try:
        r = await async_client.post(
            "/api/v1/speech/coqui/tts",
            json={"text": "hello"},
            headers=auth_headers,
        )
        assert r.status_code == 503
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_coqui_tts_local_http_hits_sidecar_ok(
    async_client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uses real synthesize_single_xtts_clip with patched httpx client."""
    from friday_api.config import get_settings

    class FakeResp:
        status_code = 200
        content = b"\x89wavstub"

    class FakeClient:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def post(self, url: str, **_kw: object):  # noqa: ANN401
            assert "/v1/synthesize" in url
            return FakeResp()

    get_settings.cache_clear()
    monkeypatch.setenv("COQUI_TTS_BACKEND", "local_http")
    monkeypatch.setenv("COQUI_LOCAL_TTS_URL", "http://127.0.0.1:8787")
    monkeypatch.setattr("friday_api.services.coqui_xtts.httpx.AsyncClient", FakeClient)
    try:
        r = await async_client.post(
            "/api/v1/speech/coqui/tts",
            json={"text": "hello"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("audio/wav")
        assert bytes(r.content) == b"\x89wavstub"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_coqui_tts_backend_aliases_local(monkeypatch: pytest.MonkeyPatch) -> None:
    from friday_api.config import get_settings

    monkeypatch.setenv("COQUI_TTS_BACKEND", "local")
    monkeypatch.setenv("COQUI_LOCAL_TTS_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()

    class FakeResp:
        status_code = 200
        content = b"ok"

    class FakeClient:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def post(self, *_a: object, **_kw: object):
            return FakeResp()

    try:
        from friday_api.services.coqui_xtts import synthesize_single_xtts_clip

        monkeypatch.setattr("friday_api.services.coqui_xtts.httpx.AsyncClient", FakeClient)
        out = await synthesize_single_xtts_clip("hi")
        assert out == b"ok"
    finally:
        get_settings.cache_clear()
