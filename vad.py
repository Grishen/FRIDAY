"""Voice Activity Detection with multi-backend fallbacks.

Backends (chosen in order):
1. ``silero`` (neural, best accuracy) — `pip install silero-vad torch`
2. ``webrtc``  — `pip install webrtcvad` (fast, deterministic)
3. ``rms``     — simple energy threshold (always works, zero deps)

API:
    vad = make_vad()
    is_speech = vad.is_speech(pcm16_bytes, sample_rate)

All implementations accept 16-bit PCM mono. Frame size should be 10/20/30 ms
for webrtcvad; silero accepts ~30 ms windows; rms works for any chunk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def configured_backend() -> str:
    return (os.environ.get("JARVIS_VAD_BACKEND", "auto").strip().lower() or "auto")


def available_backends() -> list[str]:
    out = []
    if _has("silero_vad") or (_has("torch") and _has("torchaudio")):
        out.append("silero")
    if _has("webrtcvad"):
        out.append("webrtc")
    out.append("rms")  # always available
    return out


def chosen_backend() -> str:
    pref = configured_backend()
    avail = available_backends()
    if pref != "auto" and pref in avail:
        return pref
    return avail[0]


# --------------------------------------------------------------------------- #
# Implementations
# --------------------------------------------------------------------------- #


@dataclass
class RMSConfig:
    threshold: float = 350.0  # int16 RMS units; calibrate via adjust_for_ambient()
    min_consecutive: int = 1


class _RMSVad:
    name = "rms"

    def __init__(self, cfg: Optional[RMSConfig] = None):
        self.cfg = cfg or RMSConfig()
        self._noise_floor: float = 0.0

    def adjust_for_ambient(self, pcm: bytes) -> None:
        """Calibrate threshold from a short noise sample."""
        rms = _rms_int16(pcm)
        self._noise_floor = max(self._noise_floor, rms)
        # Set speech threshold above the noise floor.
        self.cfg.threshold = max(self.cfg.threshold, rms * 3.5 + 100.0)

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        return _rms_int16(pcm) >= self.cfg.threshold


class _WebRtcVad:
    name = "webrtc"

    def __init__(self, aggressiveness: int = 2):
        import webrtcvad  # type: ignore

        self.v = webrtcvad.Vad(max(0, min(3, int(aggressiveness))))

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        # webrtcvad expects exact 10/20/30 ms frames at 8/16/32/48 kHz.
        try:
            return self.v.is_speech(pcm, sample_rate)
        except Exception:
            return False


class _SileroVad:
    name = "silero"

    def __init__(self):
        try:
            from silero_vad import load_silero_vad, get_speech_timestamps  # type: ignore

            self._load_silero_vad = load_silero_vad
            self._get_speech_timestamps = get_speech_timestamps
            self.model = load_silero_vad()
            self._impl = "silero_vad_pkg"
        except Exception:
            import torch  # type: ignore

            self.model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
            (self._get_speech_timestamps, _, _, _, _) = utils
            self._impl = "torch_hub"

    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        import numpy as np  # type: ignore
        import torch  # type: ignore

        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if arr.size == 0:
            return False
        tensor = torch.from_numpy(arr)
        ts = self._get_speech_timestamps(
            tensor, self.model,
            sampling_rate=sample_rate,
            threshold=float(os.environ.get("JARVIS_VAD_SILERO_THRESH", "0.5")),
        )
        return bool(ts)


def _rms_int16(pcm: bytes) -> float:
    import struct

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


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def make_vad():
    backend = chosen_backend()
    if backend == "silero":
        try:
            return _SileroVad()
        except Exception:
            pass
    if backend == "webrtc":
        try:
            aggr = int(os.environ.get("JARVIS_VAD_WEBRTC_AGGRESSIVENESS", "2"))
            return _WebRtcVad(aggressiveness=aggr)
        except Exception:
            pass
    return _RMSVad()


__all__ = [
    "RMSConfig",
    "available_backends",
    "chosen_backend",
    "configured_backend",
    "make_vad",
]
