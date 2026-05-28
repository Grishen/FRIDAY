"""Microphone capture with VAD-based end-of-utterance detection.

Pulls audio in small chunks (default 30ms), uses :mod:`vad` to find the start
and end of speech, then hands off the buffered PCM to :mod:`stt_whisper` for
transcription. Designed to feel responsive: stops as soon as the user pauses
``silence_ms`` past the end of speech, not after a hard timeout.

Two capture paths:

- ``sounddevice``  — preferred (`pip install sounddevice`); low latency.
- ``pyaudio``      — fallback (already a dep of speech_recognition typically).

Both produce identical PCM16-LE mono audio.

Top-level call::

    text, info = listen_once()
    # info: {'backend', 'duration_ms', 'sample_rate', 'rms_peak'}

Env knobs:
    JARVIS_STT_SAMPLE_RATE   default 16000
    JARVIS_STT_FRAME_MS      default 30   (10/20/30 for webrtcvad)
    JARVIS_STT_MAX_SECONDS   default 30   (hard cap on a single utterance)
    JARVIS_STT_PRE_ROLL_MS   default 300  (pre-roll buffered before speech)
    JARVIS_STT_SILENCE_MS    default 700  (silence required to end utterance)
    JARVIS_STT_START_TIMEOUT default 8    (seconds to wait for speech to start)
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Optional


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


SAMPLE_RATE = _env_int("JARVIS_STT_SAMPLE_RATE", 16000)
FRAME_MS = _env_int("JARVIS_STT_FRAME_MS", 30)
MAX_SECONDS = _env_float("JARVIS_STT_MAX_SECONDS", 30.0)
PRE_ROLL_MS = _env_int("JARVIS_STT_PRE_ROLL_MS", 300)
SILENCE_MS = _env_int("JARVIS_STT_SILENCE_MS", 700)
START_TIMEOUT = _env_float("JARVIS_STT_START_TIMEOUT", 8.0)


def _frame_bytes() -> int:
    return int(SAMPLE_RATE * (FRAME_MS / 1000.0)) * 2  # 16-bit mono = 2 bytes/sample


def _samples_per_frame() -> int:
    return int(SAMPLE_RATE * (FRAME_MS / 1000.0))


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


# --------------------------------------------------------------------------- #
# Audio source abstraction
# --------------------------------------------------------------------------- #


class _SoundDeviceSource:
    name = "sounddevice"

    def __init__(self):
        import sounddevice as sd  # type: ignore

        self._sd = sd
        self._stream = None
        self._buf: deque[bytes] = deque()
        self._device = None
        try:
            from mic_profile import resolve_input_device_index

            self._device = resolve_input_device_index()
        except Exception:
            self._device = None

    def __enter__(self):
        import numpy as np  # type: ignore

        def _cb(indata, frames, time_info, status):  # noqa: ARG001
            pcm = (indata[:, 0] * 32767.0).astype("int16").tobytes() \
                if indata.dtype.kind == "f" else indata.tobytes()
            try:
                from mic_profile import process_pcm

                pcm = process_pcm(pcm, sample_rate=SAMPLE_RATE)
            except Exception:
                pass
            self._buf.append(pcm)

        kwargs = {
            "samplerate": SAMPLE_RATE,
            "channels": 1,
            "dtype": "int16",
            "blocksize": _samples_per_frame(),
            "callback": _cb,
        }
        if self._device is not None:
            kwargs["device"] = self._device
        self._stream = self._sd.InputStream(**kwargs)
        self._stream.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        finally:
            self._stream = None

    def read_frame(self, timeout: float = 0.2) -> Optional[bytes]:
        deadline = time.time() + timeout
        while not self._buf and time.time() < deadline:
            time.sleep(0.005)
        if not self._buf:
            return None
        return self._buf.popleft()


class _PyAudioSource:
    name = "pyaudio"

    def __init__(self):
        import pyaudio  # type: ignore

        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._format = pyaudio.paInt16
        self._device = None
        try:
            from mic_profile import resolve_input_device_index

            self._device = resolve_input_device_index()
        except Exception:
            self._device = None

    def __enter__(self):
        kwargs = {
            "format": self._format,
            "channels": 1,
            "rate": SAMPLE_RATE,
            "input": True,
            "frames_per_buffer": _samples_per_frame(),
        }
        if self._device is not None:
            kwargs["input_device_index"] = self._device
        self._stream = self._pa.open(**kwargs)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
        finally:
            self._stream = None
            try:
                self._pa.terminate()
            except Exception:
                pass

    def read_frame(self, timeout: float = 0.2) -> Optional[bytes]:  # noqa: ARG002
        if self._stream is None:
            return None
        try:
            pcm = self._stream.read(_samples_per_frame(), exception_on_overflow=False)
            try:
                from mic_profile import process_pcm

                pcm = process_pcm(pcm, sample_rate=SAMPLE_RATE)
            except Exception:
                pass
            return pcm
        except Exception:
            return None


def _open_source():
    if _has("sounddevice"):
        return _SoundDeviceSource()
    if _has("pyaudio"):
        return _PyAudioSource()
    raise RuntimeError(
        "No audio capture library available. Install one of: "
        "`pip install sounddevice` (recommended) or `pip install pyaudio`."
    )


def has_capture_backend() -> bool:
    return _has("sounddevice") or _has("pyaudio")


# --------------------------------------------------------------------------- #
# Capture loop with VAD
# --------------------------------------------------------------------------- #


def listen_once(*, on_listening=None, on_started=None, on_backchannel=None) -> tuple[str, dict]:
    """
    Capture a single utterance from the mic using VAD, then transcribe.

    Returns ``(text, info)``. Empty ``text`` means timeout or recognition failure.
    """
    from vad import make_vad, chosen_backend as vad_backend
    from stt_whisper import transcribe_pcm16, chosen_backend as stt_backend

    if not has_capture_backend():
        return "", {"error": "no audio capture backend (install sounddevice or pyaudio)"}

    vad = make_vad()
    pre_roll_frames = max(1, int(PRE_ROLL_MS / FRAME_MS))
    silence_frames = max(1, int(SILENCE_MS / FRAME_MS))
    max_frames = int(MAX_SECONDS * 1000 / FRAME_MS)

    pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
    speech_buf: list[bytes] = []
    info: dict = {
        "vad_backend": vad_backend(),
        "stt_backend": stt_backend(),
        "sample_rate": SAMPLE_RATE,
    }

    if on_listening:
        try:
            on_listening()
        except Exception:
            pass

    started = False
    silence_run = 0
    frame_count = 0
    t_start = time.time()
    speech_started_at: Optional[float] = None
    backchannel_sent = False
    _paused_sm = False

    try:
        from sound_monitor import pause_global, resume_global

        pause_global()
        _paused_sm = True
    except Exception:
        pass

    try:
        with _open_source() as src:
            # Adaptive calibration for RMS VAD using first ~150 ms of silence.
            if getattr(vad, "name", "") == "rms":
                try:
                    calib_frames = max(1, int(150 / FRAME_MS))
                    for _ in range(calib_frames):
                        f = src.read_frame(timeout=0.4)
                        if f:
                            vad.adjust_for_ambient(f)
                except Exception:
                    pass

            while True:
                if not started and (time.time() - t_start) > START_TIMEOUT:
                    info["error"] = "start_timeout"
                    return "", info
                if frame_count >= max_frames:
                    break

                frame = src.read_frame(timeout=0.4)
                if frame is None:
                    if started:
                        silence_run += 1
                        if silence_run >= silence_frames:
                            break
                    continue
                frame_count += 1

                if not started:
                    pre_roll.append(frame)
                    if vad.is_speech(frame, SAMPLE_RATE):
                        started = True
                        speech_buf.extend(pre_roll)
                        speech_buf.append(frame)
                        silence_run = 0
                        speech_started_at = time.time()
                        if on_started:
                            try:
                                on_started()
                            except Exception:
                                pass
                else:
                    speech_buf.append(frame)
                    if vad.is_speech(frame, SAMPLE_RATE):
                        silence_run = 0
                        if (
                            on_backchannel
                            and speech_started_at
                            and not backchannel_sent
                        ):
                            elapsed = time.time() - speech_started_at
                            try:
                                if on_backchannel(elapsed):
                                    backchannel_sent = True
                            except Exception:
                                pass
                    else:
                        silence_run += 1
                        if silence_run >= silence_frames:
                            break
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"capture failed: {exc}"
        return "", info
    finally:
        if _paused_sm:
            try:
                from sound_monitor import resume_global

                resume_global()
            except Exception:
                pass

    if not speech_buf:
        info["error"] = "no_speech"
        return "", info

    pcm = b"".join(speech_buf)
    info["duration_ms"] = int(1000 * len(pcm) / 2 / SAMPLE_RATE)
    if os.environ.get("JARVIS_SPEAKER_ID", "auto").strip().lower() not in ("0", "false", "no", "off"):
        info["pcm"] = pcm

    result = transcribe_pcm16(pcm, SAMPLE_RATE)
    info["stt_backend"] = result.backend
    info["transcribe_ms"] = int(result.duration_s * 1000)
    if result.error:
        info["stt_error"] = result.error
    return (result.text or "").strip(), info


def describe_runtime() -> str:
    from vad import chosen_backend as vb, available_backends as va
    from stt_whisper import chosen_backend as sb, available_backends as sa

    cap = "sounddevice" if _has("sounddevice") else ("pyaudio" if _has("pyaudio") else "none")
    return (f"capture={cap}  vad={vb()} ({','.join(va())})  "
            f"stt={sb()} ({','.join(sa())})")


__all__ = [
    "has_capture_backend",
    "describe_runtime",
    "listen_once",
    "SAMPLE_RATE",
    "FRAME_MS",
    "MAX_SECONDS",
    "PRE_ROLL_MS",
    "SILENCE_MS",
    "START_TIMEOUT",
]
