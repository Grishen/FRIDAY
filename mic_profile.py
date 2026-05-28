"""Microphone input profile — device pick, gain, noise gate, light high-pass.

Improves capture in noisy rooms and lets you pin a specific mic (e.g. a
directional USB mic vs. the laptop array).

Env:
    JARVIS_MIC_DEVICE          index or name substring (sounddevice / pyaudio)
    JARVIS_MIC_GAIN            linear gain multiplier (default 1.0)
    JARVIS_MIC_NOISE_GATE      int16 RMS floor; frames below are zeroed (0=off)
    JARVIS_MIC_HIGHPASS=1      gentle high-pass (~120 Hz) — reduces rumble/HVAC
    JARVIS_MIC_AUTO_GAIN=0     normalize quiet speech toward target RMS
"""

from __future__ import annotations

import os
import struct
from typing import Optional


def _rms_int16(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    if not samples:
        return 0.0
    s = sum(x * x for x in samples)
    return (s / len(samples)) ** 0.5


def _mul_int16(pcm: bytes, gain: float) -> bytes:
    n = len(pcm) // 2
    if n == 0:
        return pcm
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    out = [max(-32768, min(32767, int(s * gain))) for s in samples]
    return struct.pack(f"<{n}h", *out)


_HP_STATE: Optional[tuple[float, float]] = None


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def gain() -> float:
    return max(0.1, min(8.0, _env_float("JARVIS_MIC_GAIN", 1.0)))


def noise_gate_rms() -> float:
    return max(0.0, _env_float("JARVIS_MIC_NOISE_GATE", 0.0))


def highpass_enabled() -> bool:
    return os.environ.get("JARVIS_MIC_HIGHPASS", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def auto_gain_enabled() -> bool:
    return os.environ.get("JARVIS_MIC_AUTO_GAIN", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def device_spec() -> str:
    return os.environ.get("JARVIS_MIC_DEVICE", "").strip()


def list_input_devices() -> list[dict]:
    """Return capture devices from sounddevice (preferred) or pyaudio."""
    out: list[dict] = []
    try:
        import sounddevice as sd  # type: ignore

        for i, dev in enumerate(sd.query_devices()):
            if int(dev.get("max_input_channels") or 0) < 1:
                continue
            out.append({
                "index": i,
                "name": str(dev.get("name") or ""),
                "channels": int(dev.get("max_input_channels") or 0),
                "sample_rate": float(dev.get("default_samplerate") or 0),
                "backend": "sounddevice",
            })
        return out
    except Exception:
        pass
    try:
        import pyaudio  # type: ignore

        pa = pyaudio.PyAudio()
        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if int(info.get("maxInputChannels") or 0) < 1:
                    continue
                out.append({
                    "index": i,
                    "name": str(info.get("name") or ""),
                    "channels": int(info.get("maxInputChannels") or 0),
                    "sample_rate": float(info.get("defaultSampleRate") or 0),
                    "backend": "pyaudio",
                })
        finally:
            pa.terminate()
    except Exception:
        pass
    return out


def resolve_input_device_index() -> Optional[int]:
    """Resolve ``JARVIS_MIC_DEVICE`` to a device index, or None for default."""
    spec = device_spec()
    if not spec:
        return None
    try:
        return int(spec)
    except ValueError:
        needle = spec.lower()
        devices = list_input_devices()
        for dev in devices:
            if needle in (dev.get("name") or "").lower():
                return int(dev["index"])
    return None


def describe_mic_profile() -> str:
    dev_idx = resolve_input_device_index()
    dev_name = "system default"
    if dev_idx is not None:
        for d in list_input_devices():
            if d.get("index") == dev_idx:
                dev_name = f"#{dev_idx} {d.get('name')}"
                break
    bits = [
        f"device={dev_name}",
        f"gain={gain():.2f}",
        f"noise_gate={noise_gate_rms():.0f}",
        f"highpass={'on' if highpass_enabled() else 'off'}",
        f"auto_gain={'on' if auto_gain_enabled() else 'off'}",
    ]
    return "Mic profile: " + ", ".join(bits)


def _highpass(pcm: bytes, sample_rate: int) -> bytes:
    """Single-pole high-pass — cheap rumble rejection."""
    global _HP_STATE
    if not pcm or sample_rate <= 0:
        return pcm
    n = len(pcm) // 2
    if n == 0:
        return pcm
    samples = list(struct.unpack(f"<{n}h", pcm[: n * 2]))
    # Cutoff ~120 Hz
    rc = 1.0 / (2.0 * 3.14159265 * 120.0)
    dt = 1.0 / float(sample_rate)
    alpha = rc / (rc + dt)
    prev_x, prev_y = _HP_STATE if _HP_STATE else (0.0, 0.0)
    out: list[int] = []
    for raw in samples:
        x = raw / 32768.0
        y = alpha * (prev_y + x - prev_x)
        prev_x, prev_y = x, y
        clipped = max(-1.0, min(1.0, y))
        out.append(int(clipped * 32767.0))
    _HP_STATE = (prev_x, prev_y)
    return struct.pack(f"<{len(out)}h", *out)


def process_pcm(pcm: bytes, *, sample_rate: int = 16000) -> bytes:
    """Apply configured mic chain to a PCM16 mono frame."""
    if not pcm:
        return pcm

    gate = noise_gate_rms()
    if gate > 0 and _rms_int16(pcm) < gate:
        return b"\x00" * len(pcm)

    if highpass_enabled():
        pcm = _highpass(pcm, sample_rate)

    g = gain()
    if auto_gain_enabled():
        rms = _rms_int16(pcm)
        target = 2500.0
        if 80.0 < rms < target:
            g *= min(4.0, target / rms)
    if abs(g - 1.0) > 0.01:
        pcm = _mul_int16(pcm, g)

    if g > 1.5:
        n = len(pcm) // 2
        if n:
            samples = struct.unpack(f"<{n}h", pcm[: n * 2])
            pcm = struct.pack(f"<{n}h", *[max(-32768, min(32767, s)) for s in samples])
    return pcm


__all__ = [
    "describe_mic_profile",
    "device_spec",
    "list_input_devices",
    "process_pcm",
    "resolve_input_device_index",
]
