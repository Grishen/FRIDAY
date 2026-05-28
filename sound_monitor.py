"""Ambient sound monitor — surfaces loud / sustained sounds without holding the mic.

Strategy:
- Open a low-bitrate, low-CPU PCM stream (16 kHz mono, 100 ms frames).
- Maintain a running noise-floor RMS estimate (slow EMA).
- A "loud burst" event fires when current RMS exceeds floor * trigger_ratio for
  ``min_duration_ms`` consecutive frames.
- After firing, capture ~1.5 s of audio and (optionally) classify it via Whisper
  ("doorbell", "phone ringing", "alarm" hints) or just surface a generic alert.
- Per-event cooldown prevents spam.

The monitor *yields control of the mic whenever it isn't actively sampling*,
so it composes cleanly with the regular voice loop (we briefly suspend it
during ``listen_once``).

Usage:
    sm = SoundMonitor(on_event=lambda kind, transcript: ...)
    sm.start()
    ...
    sm.pause(); ...; sm.resume()
    sm.stop()
"""

from __future__ import annotations

import os
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


def _env_float(k: str, default: float) -> float:
    try:
        return float(os.environ.get(k, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(k: str, default: int) -> int:
    try:
        return int(os.environ.get(k, str(default)))
    except (TypeError, ValueError):
        return default


SAMPLE_RATE = _env_int("JARVIS_SOUND_SAMPLE_RATE", 16000)
FRAME_MS = _env_int("JARVIS_SOUND_FRAME_MS", 100)
TRIGGER_RATIO = _env_float("JARVIS_SOUND_TRIGGER_RATIO", 4.5)
MIN_DURATION_MS = _env_int("JARVIS_SOUND_MIN_MS", 220)
COOLDOWN_S = _env_float("JARVIS_SOUND_COOLDOWN_S", 30.0)
NOISE_EMA_ALPHA = _env_float("JARVIS_SOUND_NOISE_ALPHA", 0.02)
CLIP_S = _env_float("JARVIS_SOUND_CLIP_S", 1.5)


@dataclass
class SoundEvent:
    kind: str  # 'burst' | 'doorbell' | 'alarm' | 'phone' | 'speech'
    peak_rms: float
    duration_ms: int
    transcript: str = ""
    ts: float = 0.0


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def _rms_int16(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"{n}h", pcm[: n * 2])
    sq = 0
    for s in samples:
        sq += s * s
    return (sq / n) ** 0.5


_GLOBAL_MONITOR: Optional["SoundMonitor"] = None


def register_global(monitor: "SoundMonitor") -> None:
    global _GLOBAL_MONITOR
    _GLOBAL_MONITOR = monitor


def pause_global() -> None:
    if _GLOBAL_MONITOR is not None:
        _GLOBAL_MONITOR.pause()


def resume_global() -> None:
    if _GLOBAL_MONITOR is not None:
        _GLOBAL_MONITOR.resume()


class SoundMonitor:
    def __init__(self, on_event: Optional[Callable[[SoundEvent], None]] = None,
                 *, classify: bool = True):
        self.on_event = on_event
        self.classify = classify
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._noise_floor: float = 200.0
        self._last_event_at: float = 0.0

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        if not (_has("sounddevice") or _has("pyaudio")):
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sound-monitor", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.0)
        self._thread = None

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- core loop --------------------------------------------------------

    def _open_source(self):
        try:
            from stt_capture import _open_source as open_src  # reuse capture abstraction
            return open_src()
        except Exception:
            return None

    def _run(self) -> None:
        src = self._open_source()
        if src is None:
            return
        try:
            with src as s:
                while not self._stop.is_set():
                    if self._pause.is_set():
                        time.sleep(0.1)
                        continue
                    frame = s.read_frame(timeout=0.4)
                    if frame is None:
                        continue
                    self._process_frame(frame, s)
        except Exception:
            return

    def _process_frame(self, frame: bytes, src) -> None:
        rms = _rms_int16(frame)
        # Slow EMA noise floor.
        if rms < self._noise_floor * 2:
            self._noise_floor = (1 - NOISE_EMA_ALPHA) * self._noise_floor + NOISE_EMA_ALPHA * rms
        threshold = max(400.0, self._noise_floor * TRIGGER_RATIO)
        if rms < threshold:
            return
        # Confirm with a few more frames.
        accum = [frame]
        peak = rms
        max_frames = max(2, MIN_DURATION_MS // FRAME_MS)
        for _ in range(max_frames - 1):
            f = src.read_frame(timeout=0.2)
            if f is None:
                break
            accum.append(f)
            peak = max(peak, _rms_int16(f))
        if peak < threshold:
            return
        if (time.time() - self._last_event_at) < COOLDOWN_S:
            return
        self._last_event_at = time.time()

        # Capture an extra clip after the burst (~CLIP_S) for classification.
        extra_frames = int(CLIP_S * 1000 / FRAME_MS)
        for _ in range(extra_frames):
            if self._stop.is_set() or self._pause.is_set():
                break
            f = src.read_frame(timeout=0.2)
            if f is None:
                break
            accum.append(f)
        pcm = b"".join(accum)
        duration_ms = int(1000 * (len(pcm) // 2) / SAMPLE_RATE)

        event = SoundEvent(kind="burst", peak_rms=peak, duration_ms=duration_ms, ts=time.time())

        if self.classify:
            event = self._classify(pcm, event)

        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def _classify(self, pcm: bytes, event: SoundEvent) -> SoundEvent:
        # Cheap & cheerful: transcribe with Whisper. If we see specific keywords,
        # bump the kind. Otherwise it stays 'burst' with the transcript attached.
        try:
            from stt_whisper import transcribe_pcm16

            r = transcribe_pcm16(pcm, SAMPLE_RATE)
            text = (r.text or "").strip().lower()
            event.transcript = r.text or ""
            if any(k in text for k in ("ring", "doorbell", "knock")):
                event.kind = "doorbell"
            elif any(k in text for k in ("alarm", "siren", "beep")):
                event.kind = "alarm"
            elif any(k in text for k in ("hello", "hey", "can you hear", "are you there")):
                event.kind = "speech"
            elif "phone" in text:
                event.kind = "phone"
        except Exception:
            pass
        return event


__all__ = ["SoundEvent", "SoundMonitor", "pause_global", "register_global", "resume_global"]
