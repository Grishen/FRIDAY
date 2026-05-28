"""On-device wake word via Picovoice Porcupine (low CPU, no cloud STT).

Requires ``pip install pvporcupine`` and a Picovoice access key.

Env:
    JARVIS_PORCUPINE=1|auto          auto when JARVIS_ALWAYS_ON_WAKE is on
    PICOVOICE_ACCESS_KEY=            from console.picovoice.ai
    JARVIS_PORCUPINE_KEYWORDS=jarvis,computer   built-in keyword names
    JARVIS_PORCUPINE_MODEL=          optional path to custom .ppn (single keyword)
    JARVIS_PORCUPINE_SENSITIVITY=0.55
"""

from __future__ import annotations

import os
import struct
import threading
import time
from typing import Callable, Optional

_STOP = threading.Event()
_THREAD: Optional[threading.Thread] = None
_ON_WAKE: Optional[Callable[[], None]] = None


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def available() -> bool:
    try:
        import pvporcupine  # noqa: F401

        return bool(os.environ.get("PICOVOICE_ACCESS_KEY", "").strip())
    except ImportError:
        return False


def enabled() -> bool:
    flag = os.environ.get("JARVIS_PORCUPINE", "0").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return available()
    if flag == "auto":
        wake = os.environ.get("JARVIS_ALWAYS_ON_WAKE", "0").strip().lower()
        if wake in ("1", "true", "yes", "on", "auto"):
            return available()
    return False


def is_running() -> bool:
    return bool(_THREAD and _THREAD.is_alive())


def _keywords() -> list[str]:
    raw = os.environ.get("JARVIS_PORCUPINE_KEYWORDS", "jarvis,computer").strip()
    return [k.strip().lower() for k in raw.split(",") if k.strip()]


def _create_porcupine():
    import pvporcupine

    access_key = os.environ["PICOVOICE_ACCESS_KEY"].strip()
    sensitivity = _env_float("JARVIS_PORCUPINE_SENSITIVITY", 0.55)
    sens = [max(0.0, min(1.0, sensitivity))]

    model = os.environ.get("JARVIS_PORCUPINE_MODEL", "").strip()
    if model:
        return pvporcupine.create(
            access_key=access_key,
            keyword_paths=[os.path.expanduser(model)],
            sensitivities=sens,
        )

    keys = _keywords()
    return pvporcupine.create(
        access_key=access_key,
        keywords=keys,
        sensitivities=[sens[0]] * len(keys),
    )


def stop_porcupine_wake() -> None:
    global _THREAD
    _STOP.set()
    t = _THREAD
    if t and t.is_alive():
        t.join(timeout=2.0)
    _THREAD = None
    _STOP.clear()


def start_porcupine_wake(on_wake: Callable[[], None]) -> bool:
    """Start Porcupine listener thread. ``on_wake`` is called on detection."""
    global _THREAD, _ON_WAKE
    if not enabled():
        return False
    if is_running():
        return True
    _ON_WAKE = on_wake
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="jarvis-porcupine", daemon=True)
    _THREAD.start()
    keys = _keywords()
    model = os.environ.get("JARVIS_PORCUPINE_MODEL", "").strip()
    label = model or ", ".join(keys)
    print(f"[startup] Porcupine wake: active ({label})", flush=True)
    return True


def _loop() -> None:
    porcupine = None
    stream = None
    try:
        from mic_profile import process_pcm, resolve_input_device_index

        porcupine = _create_porcupine()
        frame_len = porcupine.frame_length
        sample_rate = porcupine.sample_rate

        import sounddevice as sd  # type: ignore
        import numpy as np  # type: ignore

        device = resolve_input_device_index()
        kwargs = {
            "samplerate": sample_rate,
            "channels": 1,
            "dtype": "int16",
            "blocksize": frame_len,
        }
        if device is not None:
            kwargs["device"] = device

        def _callback(indata, frames, time_info, status):  # noqa: ARG001
            if _STOP.is_set():
                return
            pcm = indata[:, 0].tobytes()
            pcm = process_pcm(pcm, sample_rate=sample_rate)
            samples = struct.unpack_from(f"<{frame_len}h", pcm, 0)
            idx = porcupine.process(samples)
            if idx >= 0 and _ON_WAKE:
                try:
                    _ON_WAKE()
                except Exception:
                    pass

        stream = sd.InputStream(callback=_callback, **kwargs)
        stream.start()
        while not _STOP.is_set():
            time.sleep(0.1)
    except Exception as exc:
        print(f"[porcupine_wake] failed: {exc}", flush=True)
    finally:
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception:
            pass
        try:
            if porcupine is not None:
                porcupine.delete()
        except Exception:
            pass


def describe_status() -> str:
    if not available():
        return "Porcupine unavailable — install pvporcupine and set PICOVOICE_ACCESS_KEY."
    if enabled() and is_running():
        return "Porcupine wake listener is running."
    if enabled():
        return "Porcupine enabled but not running."
    return "Porcupine wake is off."


__all__ = [
    "available",
    "describe_status",
    "enabled",
    "is_running",
    "start_porcupine_wake",
    "stop_porcupine_wake",
]
