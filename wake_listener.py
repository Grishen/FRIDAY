"""Always-on wake-word listener — low-power mic watch without full command STT.

Runs in a background thread. When speech is detected, captures a short
utterance (default ≤3 s), transcribes once, and fires if a configured wake
word is present. The main voice loop can wait on :func:`wait_for_wake` instead
of running full ``take_command()`` while idle in passive mode.

Env:
    JARVIS_ALWAYS_ON_WAKE=1|auto   auto starts when JARVIS_PASSIVE_MODE=1
    JARVIS_WAKE_WORD               comma-separated phrases (shared with main.py)
    JARVIS_WAKE_MAX_SECONDS        max capture after speech starts (default 3)
    JARVIS_WAKE_COOLDOWN           seconds between wake fires (default 1.5)
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Optional

_WAKE_LOCK = threading.Lock()
_WAKE_EVENT = threading.Event()
_AFTER_WAKE = ""
_STOP = threading.Event()
_THREAD: Optional[threading.Thread] = None
_LAST_WAKE_AT = 0.0


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _wake_words() -> list[str]:
    raw = os.environ.get("JARVIS_WAKE_WORD", "jarvis,hey jarvis,friday,hey friday").strip()
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def _strip_wake(raw: str) -> tuple[bool, str]:
    low = (raw or "").strip().lower()
    if not low:
        return False, ""
    for w in sorted(_wake_words(), key=len, reverse=True):
        if low == w:
            return True, ""
        if low.startswith(w + " "):
            return True, raw[len(w) + 1 :].strip()
        if low.startswith(w + ",") or low.startswith(w + "."):
            return True, raw[len(w) + 1 :].strip()
    return False, raw


def enabled() -> bool:
    flag = os.environ.get("JARVIS_ALWAYS_ON_WAKE", "0").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag == "auto":
        return os.environ.get("JARVIS_PASSIVE_MODE", "").strip().lower() in (
            "1", "true", "yes", "on",
        )
    return False


def is_running() -> bool:
    try:
        from porcupine_wake import is_running as porc_running

        if porc_running():
            return True
    except Exception:
        pass
    return bool(_THREAD and _THREAD.is_alive())


def pop_wake() -> tuple[bool, str]:
    """Non-blocking: return (woke, text_after_wake) and clear the signal."""
    with _WAKE_LOCK:
        if not _WAKE_EVENT.is_set():
            return False, ""
        _WAKE_EVENT.clear()
        after = _AFTER_WAKE
        return True, after


def wait_for_wake(*, timeout: Optional[float] = None) -> tuple[bool, str]:
    """Block until wake or timeout. Returns (woke, text_after_wake)."""
    fired = _WAKE_EVENT.wait(timeout=timeout)
    return pop_wake() if fired else (False, "")


def signal_wake(*, after_wake: str = "") -> None:
    global _AFTER_WAKE, _LAST_WAKE_AT
    cooldown = _env_float("JARVIS_WAKE_COOLDOWN", 1.5)
    now = time.time()
    if now - _LAST_WAKE_AT < cooldown:
        return
    _LAST_WAKE_AT = now
    with _WAKE_LOCK:
        _AFTER_WAKE = after_wake
        _WAKE_EVENT.set()


def stop_wake_listener() -> None:
    global _THREAD
    try:
        from porcupine_wake import stop_porcupine_wake

        stop_porcupine_wake()
    except Exception:
        pass
    _STOP.set()
    t = _THREAD
    if t and t.is_alive():
        t.join(timeout=2.0)
    _THREAD = None
    _STOP.clear()


def start_wake_listener() -> bool:
    """Idempotently start the background wake-word thread."""
    global _THREAD
    if not enabled():
        return False
    if is_running():
        return True

    try:
        from porcupine_wake import enabled as porc_on, start_porcupine_wake

        if porc_on():
            return start_porcupine_wake(on_wake=lambda: signal_wake(after_wake=""))
    except Exception:
        pass

    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="jarvis-wake-listener", daemon=True)
    _THREAD.start()
    print("[startup] Wake listener: active (Whisper/VAD)", flush=True)
    return True


def _loop() -> None:
    try:
        from stt_capture import SAMPLE_RATE, _frame_bytes, _open_source  # type: ignore[attr-defined]
        from vad import make_vad, vad_backend
        from stt_whisper import transcribe_pcm16
    except Exception as exc:
        print(f"[wake_listener] unavailable: {exc}", flush=True)
        return

    max_seconds = _env_float("JARVIS_WAKE_MAX_SECONDS", 3.0)
    frame_ms = max(10, int(float(os.environ.get("JARVIS_STT_FRAME_MS", "30"))))
    silence_ms = max(300, int(float(os.environ.get("JARVIS_WAKE_SILENCE_MS", "500"))))
    pre_roll_ms = max(100, int(float(os.environ.get("JARVIS_STT_PRE_ROLL_MS", "300"))))

    silence_frames = max(1, int(silence_ms / frame_ms))
    pre_roll_frames = max(1, int(pre_roll_ms / frame_ms))
    max_frames = max(5, int(max_seconds * 1000 / frame_ms))

    vad = make_vad()
    print(f"[wake_listener] VAD={vad_backend()} waiting for wake words: {', '.join(_wake_words())}",
          flush=True)

    while not _STOP.is_set():
        try:
            with _open_source() as src:
                if getattr(vad, "name", "") == "rms":
                    try:
                        for _ in range(max(1, int(150 / frame_ms))):
                            f = src.read_frame(timeout=0.3)
                            if f:
                                vad.adjust_for_ambient(f)
                    except Exception:
                        pass

                pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
                speech_buf: list[bytes] = []
                started = False
                silence_run = 0
                frame_count = 0

                while not _STOP.is_set():
                    frame = src.read_frame(timeout=0.35)
                    if frame is None:
                        if started:
                            silence_run += 1
                            if silence_run >= silence_frames:
                                break
                        continue

                    if not started:
                        pre_roll.append(frame)
                        if vad.is_speech(frame, SAMPLE_RATE):
                            started = True
                            speech_buf.extend(pre_roll)
                            speech_buf.append(frame)
                            silence_run = 0
                            frame_count = 1
                    else:
                        speech_buf.append(frame)
                        frame_count += 1
                        if vad.is_speech(frame, SAMPLE_RATE):
                            silence_run = 0
                        else:
                            silence_run += 1
                            if silence_run >= silence_frames or frame_count >= max_frames:
                                break

                if not speech_buf:
                    continue

                pcm = b"".join(speech_buf)
                try:
                    from mic_profile import process_pcm

                    pcm = process_pcm(pcm, sample_rate=SAMPLE_RATE)
                except Exception:
                    pass
                result = transcribe_pcm16(pcm, SAMPLE_RATE)
                text = (result.text or "").strip()
                if not text:
                    continue

                woke, after = _strip_wake(text)
                if woke:
                    print(f"[wake_listener] wake detected: {text!r}", flush=True)
                    signal_wake(after_wake=after)
        except Exception:
            _STOP.wait(0.5)


__all__ = [
    "enabled",
    "is_running",
    "pop_wake",
    "signal_wake",
    "start_wake_listener",
    "stop_wake_listener",
    "wait_for_wake",
]
