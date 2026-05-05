"""FastAPI sidecar: XTTS (or compatible) → WAV.

Run in a **separate venv** where you install PyTorch + Coqui TTS from PyPI or your GitHub checkout
(see FRIDAY `.env.example`). The main `friday-api` process stays free of torch/TTS deps.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
from functools import lru_cache
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

log = structlog.get_logger("coqui.local.tts")

app = FastAPI(title="FRIDAY Coqui local TTS", version="0.1.0")


class SynthesizeIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=520)
    language: str = "en"
    speed: float = Field(default=1.0, ge=0.0, le=2.0)


@lru_cache
def _speaker_path() -> Path:
    raw = os.environ.get("COQUI_SPEAKER_WAV", "").strip()
    if not raw:
        raise RuntimeError("COQUI_SPEAKER_WAV_not_set")
    p = Path(raw).expanduser().resolve()
    if not p.is_file():
        raise RuntimeError(f"COQUI_SPEAKER_WAV_not_found:{p}")
    return p


@lru_cache
def _model_name() -> str:
    return os.environ.get(
        "COQUI_XTTS_MODEL",
        "tts_models/multilingual/multi-dataset/xtts_v2",
    ).strip()


@lru_cache
def _use_gpu() -> bool:
    return os.environ.get("COQUI_USE_GPU", "false").strip().lower() in ("1", "true", "yes")


_tts_singleton: object | None = None


def _get_tts_engine():
    """Import and construct TTS once per process (heavy)."""
    global _tts_singleton
    if _tts_singleton is not None:
        return _tts_singleton
    try:
        from TTS.api import TTS
    except ImportError as e:
        raise RuntimeError(
            "Coqui TTS is not installed in this environment. "
            "Install PyTorch, then `pip install -e /path/to/your/TTS` "
            "or `pip install git+https://github.com/coqui-ai/TTS.git` (see Coqui docs)."
        ) from e

    model = _model_name()
    gpu = _use_gpu()
    log.info("tts_model_load", model=model, gpu=gpu)
    try:
        _tts_singleton = TTS(model_name=model, gpu=gpu)
    except TypeError:
        _tts_singleton = TTS(model_name=model)
    return _tts_singleton


def _tts_to_wav_bytes(tts, text: str, language: str, speaker: Path) -> bytes:
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        if "xtts" in _model_name().lower():
            try:
                tts.tts_to_file(text=text, file_path=tmp, speaker_wav=str(speaker), language=language)
            except TypeError:
                tts.tts_to_file(text=text, file_path=tmp, speaker_wav=[str(speaker)], language=language)
        else:
            # Non-XTTS models: caller should point COQUI_XTTS_MODEL at a single-speaker model.
            tts.tts_to_file(text=text, file_path=tmp)

        # speed: not consistently supported across APIs; omit unless we extend later.

        return Path(tmp).read_bytes()
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass


@app.get("/health")
async def health() -> JSONResponse:
    detail: dict = {"model": _model_name()}
    try:
        detail["speaker_wav"] = str(_speaker_path())
    except RuntimeError as e:
        return JSONResponse({"status": "degraded", "detail": str(e), **detail}, status_code=503)
    try:
        importlib.import_module("TTS")
    except ImportError as e:
        return JSONResponse(
            {"status": "degraded", "detail": f"tts_package_missing:{e!s}", **detail},
            status_code=503,
        )
    return JSONResponse({"status": "ok", **detail})


@app.post("/v1/synthesize")
async def synthesize(body: SynthesizeIn) -> Response:
    try:
        speaker = _speaker_path()
        tts = _get_tts_engine()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty_text")

    try:
        data = await asyncio.to_thread(_tts_to_wav_bytes, tts, text, body.language.strip() or "en", speaker)
    except Exception as e:
        log.exception("tts_inference_failed")
        raise HTTPException(status_code=502, detail=f"tts_inference:{e!s}") from e

    if not data:
        raise HTTPException(status_code=502, detail="empty_waveform")

    return Response(content=data, media_type="audio/wav", headers={"Cache-Control": "no-store"})


def dev() -> None:
    import uvicorn

    port = int(os.environ.get("COQUI_LOCAL_PORT", "8787"))
    uvicorn.run("coqui_local_tts.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    dev()
