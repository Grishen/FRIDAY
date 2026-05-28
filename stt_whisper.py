"""Speech-to-text backends with graceful fallbacks.

Backend preference (set via ``JARVIS_STT_BACKEND``; default ``auto``):

    auto             — first available of: faster_whisper → whisper → openai_api → google
    faster_whisper   — `pip install faster-whisper`   (best: fast, accurate, offline)
    whisper          — `pip install openai-whisper`   (offline but slower)
    openai_api       — uses OpenAI Audio transcriptions endpoint (online, accurate)
    google           — legacy free Google web API via SpeechRecognition (no install needed)

Other env knobs:
    JARVIS_WHISPER_MODEL    — model name (default 'base.en' for faster-whisper, 'base' for whisper, 'whisper-1' for API)
    JARVIS_WHISPER_DEVICE   — cpu | cuda | auto  (default 'auto')
    JARVIS_WHISPER_LANG     — language hint (default 'en'; '' = auto-detect)
    JARVIS_WHISPER_COMPUTE  — int8 | int8_float16 | float16 | float32 (faster-whisper only)

Audio format expected by ``transcribe_pcm16``:
    PCM16 mono little-endian bytes + sample rate (typically 16000 Hz).
"""

from __future__ import annotations

import io
import os
import tempfile
import time
import wave
from dataclasses import dataclass
from typing import Optional


# --------------------------------------------------------------------------- #
# Configuration helpers
# --------------------------------------------------------------------------- #


@dataclass
class STTResult:
    text: str
    language: Optional[str] = None
    backend: str = ""
    duration_s: float = 0.0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error


def configured_backend() -> str:
    return (os.environ.get("JARVIS_STT_BACKEND", "auto").strip().lower() or "auto")


def _whisper_lang() -> Optional[str]:
    lang = os.environ.get("JARVIS_WHISPER_LANG", "en").strip()
    return lang or None


def _whisper_device() -> str:
    return (os.environ.get("JARVIS_WHISPER_DEVICE", "auto").strip().lower() or "auto")


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def available_backends() -> list[str]:
    """Return backends in preference order (local/free before paid cloud APIs)."""
    out: list[str] = []
    if _has("faster_whisper"):
        out.append("faster_whisper")
    if _has("whisper"):
        out.append("whisper")
    if _has("speech_recognition"):
        out.append("google")
    if os.environ.get("OPENAI_API_KEY", "").strip() and _has("openai"):
        out.append("openai_api")
    return out


def _is_retriable_stt_error(error: Optional[str]) -> bool:
    if not error:
        return False
    low = error.lower()
    needles = (
        "429", "402", "quota", "insufficient_quota", "payment required",
        "billing", "rate limit", "rate_limit", "exceeded",
    )
    return any(n in low for n in needles)


def _backend_try_order() -> list[str]:
    """Ordered backends to attempt for this transcription."""
    pref = configured_backend()
    avail = available_backends()
    if pref != "auto" and pref in avail:
        # Explicit preference first, then fallbacks.
        rest = [b for b in avail if b != pref]
        return [pref] + rest
    return list(avail)


def chosen_backend() -> str:
    """Resolve the configured backend, falling back through availability."""
    pref = configured_backend()
    avail = available_backends()
    if pref != "auto" and pref in avail:
        return pref
    return avail[0] if avail else "none"


# --------------------------------------------------------------------------- #
# Audio helpers
# --------------------------------------------------------------------------- #


def pcm16_to_wav_bytes(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm)
    return buf.getvalue()


def pcm16_to_float32(pcm: bytes):
    """Convert PCM16LE bytes to a numpy float32 array in [-1, 1]."""
    import numpy as np  # type: ignore

    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return arr


# --------------------------------------------------------------------------- #
# Cached model holders (one model per backend per process)
# --------------------------------------------------------------------------- #


_FW_MODEL = None
_WHISPER_MODEL = None


def _load_faster_whisper():
    global _FW_MODEL
    if _FW_MODEL is not None:
        return _FW_MODEL
    from faster_whisper import WhisperModel  # type: ignore

    model_name = os.environ.get("JARVIS_WHISPER_MODEL", "base.en").strip() or "base.en"
    device = _whisper_device()
    if device == "auto":
        device = "cpu"  # safe default; users can opt into 'cuda' explicitly
    compute = os.environ.get("JARVIS_WHISPER_COMPUTE", "int8").strip() or "int8"
    _FW_MODEL = WhisperModel(model_name, device=device, compute_type=compute)
    return _FW_MODEL


def _load_whisper():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    import whisper  # type: ignore

    model_name = os.environ.get("JARVIS_WHISPER_MODEL", "base").strip() or "base"
    _WHISPER_MODEL = whisper.load_model(model_name)
    return _WHISPER_MODEL


# --------------------------------------------------------------------------- #
# Backend implementations
# --------------------------------------------------------------------------- #


def _transcribe_faster_whisper(pcm: bytes, sample_rate: int) -> STTResult:
    t0 = time.time()
    try:
        model = _load_faster_whisper()
        audio = pcm16_to_float32(pcm)
        segments, info = model.transcribe(
            audio,
            language=_whisper_lang(),
            vad_filter=False,  # we already do VAD upstream
            beam_size=1,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return STTResult(text=text, language=getattr(info, "language", None),
                         backend="faster_whisper", duration_s=time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        return STTResult(text="", backend="faster_whisper", error=str(exc),
                         duration_s=time.time() - t0)


def _transcribe_whisper(pcm: bytes, sample_rate: int) -> STTResult:
    t0 = time.time()
    try:
        import whisper  # type: ignore  # noqa: F401

        model = _load_whisper()
        audio = pcm16_to_float32(pcm)
        result = model.transcribe(audio, language=_whisper_lang(), fp16=False)
        text = (result.get("text") or "").strip()
        return STTResult(text=text, language=result.get("language"),
                         backend="whisper", duration_s=time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        return STTResult(text="", backend="whisper", error=str(exc),
                         duration_s=time.time() - t0)


def _transcribe_openai_api(pcm: bytes, sample_rate: int) -> STTResult:
    t0 = time.time()
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return STTResult(text="", backend="openai_api",
                         error="OPENAI_API_KEY not set", duration_s=0.0)
    try:
        from openai import OpenAI

        wav_bytes = pcm16_to_wav_bytes(pcm, sample_rate)
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(wav_bytes)
            path = tf.name
        try:
            with open(path, "rb") as fh:
                model = os.environ.get("JARVIS_WHISPER_MODEL", "whisper-1").strip() or "whisper-1"
                resp = client.audio.transcriptions.create(
                    model=model,
                    file=fh,
                    language=_whisper_lang() or None,
                )
            text = (getattr(resp, "text", "") or "").strip()
            return STTResult(text=text, backend="openai_api",
                             duration_s=time.time() - t0)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001
        return STTResult(text="", backend="openai_api", error=str(exc),
                         duration_s=time.time() - t0)


def _transcribe_google(pcm: bytes, sample_rate: int) -> STTResult:
    t0 = time.time()
    try:
        import speech_recognition as sr  # type: ignore

        wav_bytes = pcm16_to_wav_bytes(pcm, sample_rate)
        r = sr.Recognizer()
        with io.BytesIO(wav_bytes) as buf, sr.AudioFile(buf) as src:
            audio = r.record(src)
        text = r.recognize_google(audio, language=os.environ.get("JARVIS_GOOGLE_STT_LANG", "en-US"))
        return STTResult(text=(text or "").strip(), backend="google",
                         duration_s=time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        return STTResult(text="", backend="google", error=str(exc),
                         duration_s=time.time() - t0)


_DISPATCH = {
    "faster_whisper": _transcribe_faster_whisper,
    "whisper": _transcribe_whisper,
    "openai_api": _transcribe_openai_api,
    "google": _transcribe_google,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def transcribe_pcm16(pcm: bytes, sample_rate: int = 16000) -> STTResult:
    """Transcribe PCM16 mono — tries backends in order with fallback on API errors."""
    if not pcm or len(pcm) < 32:
        return STTResult(text="", backend="none", error="empty audio")

    order = _backend_try_order()
    if not order:
        return STTResult(
            text="",
            backend="none",
            error="No STT backend available. Install faster-whisper or speech_recognition.",
        )

    last: Optional[STTResult] = None
    errors: list[str] = []
    for backend in order:
        fn = _DISPATCH.get(backend)
        if fn is None:
            continue
        result = fn(pcm, sample_rate)
        if result.ok:
            if errors:
                print(
                    f"[stt] recovered via {backend} after: {'; '.join(errors[-2:])}",
                    flush=True,
                )
            return result
        last = result
        err = result.error or "no text"
        errors.append(f"{backend}: {err[:120]}")
        # Only keep trying when the failure looks like a billing/quota/transient API issue.
        if not _is_retriable_stt_error(result.error):
            break

    if last:
        combined = "; ".join(errors) if errors else (last.error or "transcription failed")
        return STTResult(
            text="",
            backend=last.backend or order[-1],
            error=combined,
            duration_s=last.duration_s,
        )
    return STTResult(text="", backend="none", error="transcription failed")


def describe_backend_choice() -> str:
    return (
        f"STT backend: {chosen_backend()} "
        f"(configured={configured_backend()}, available={', '.join(available_backends()) or 'none'})"
    )


__all__ = [
    "STTResult",
    "available_backends",
    "chosen_backend",
    "configured_backend",
    "describe_backend_choice",
    "pcm16_to_float32",
    "pcm16_to_wav_bytes",
    "transcribe_pcm16",
]
