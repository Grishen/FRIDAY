"""Lightweight speaker identification for multi-user memory scoping.

Computes a cheap feature vector from each utterance and compares cosine
similarity against enrolled voiceprints (one per user). When a strong match
is found, :mod:`user_profiles` can switch the active user automatically.

Storage: ``data/jarvis_voiceprints.json``::

    {
      "users": {
        "alice": {"voiceprint": [...], "count": 5},
        "default": {"voiceprint": [...], "count": 5}
      }
    }

Legacy single-voiceprint files are migrated on first read.

API:
    match_speaker(pcm, sample_rate) -> {user_id, similarity, enrolled}
    enroll_active_user(pcm, sample_rate) -> dict
    enroll_or_match(pcm, sample_rate) -> dict   # backwards-compatible primary
    reset_voiceprint(user_id=None)
"""

from __future__ import annotations

import json
import math
import os
import struct
from pathlib import Path
from typing import Optional

_STATE_PATH = os.path.join(os.environ.get("JARVIS_DATA_DIR", "data"), "jarvis_voiceprints.json")
_ENROLL_FRAMES = 5
_FEATURE_DIM = 8
_DEFAULT_THRESHOLD = 0.82


def _load_state() -> dict:
    if not os.path.isfile(_STATE_PATH):
        return {"users": {}}
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception:
        return {"users": {}}

    # Migrate legacy single voiceprint format.
    if "users" not in raw and raw.get("voiceprint"):
        raw = {
            "users": {
                "default": {
                    "voiceprint": raw.get("voiceprint"),
                    "count": int(raw.get("count") or 0),
                }
            }
        }
    if "users" not in raw:
        raw["users"] = {}
    return raw


def _save_state(state: dict) -> None:
    try:
        Path(os.path.dirname(_STATE_PATH) or ".").mkdir(parents=True, exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _active_user_id() -> str:
    try:
        from user_profiles import active_user

        return active_user() or "default"
    except Exception:
        return "default"


def _threshold() -> float:
    try:
        return float(os.environ.get("JARVIS_SPEAKER_THRESHOLD", str(_DEFAULT_THRESHOLD)))
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD


# --------------------------------------------------------------------------- #
# Feature extraction
# --------------------------------------------------------------------------- #


def _pcm16_to_float(pcm: bytes) -> list[float]:
    n = len(pcm) // 2
    if n == 0:
        return []
    samples = struct.unpack(f"{n}h", pcm[: n * 2])
    return [s / 32768.0 for s in samples]


def _zero_crossing_rate(samples: list[float]) -> float:
    if len(samples) < 2:
        return 0.0
    crossings = sum(1 for i in range(1, len(samples)) if (samples[i - 1] >= 0) != (samples[i] >= 0))
    return crossings / len(samples)


def _rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    s = sum(x * x for x in samples)
    return math.sqrt(s / len(samples))


def _autocorr_f0(samples: list[float], sample_rate: int, fmin: int = 70, fmax: int = 400) -> float:
    if len(samples) < sample_rate // fmin:
        return 0.0
    min_lag = sample_rate // fmax
    max_lag = sample_rate // fmin
    best_lag = 0
    best_val = -1.0
    for lag in range(min_lag, min(max_lag, len(samples) // 2)):
        val = sum(samples[i] * samples[i + lag] for i in range(len(samples) - lag))
        if val > best_val:
            best_val = val
            best_lag = lag
    if best_lag == 0:
        return 0.0
    return sample_rate / best_lag


def _spectral_centroid_simple(samples: list[float], sample_rate: int) -> float:
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return 0.0
    if not samples:
        return 0.0
    arr = np.array(samples, dtype="float32")
    n = min(8192, len(arr))
    if n < 16:
        return 0.0
    spectrum = np.abs(np.fft.rfft(arr[:n]))
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    if spectrum.sum() == 0:
        return 0.0
    return float((freqs * spectrum).sum() / spectrum.sum())


def _band_energies(samples: list[float], sample_rate: int, n_bands: int = 4) -> list[float]:
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return [0.0] * n_bands
    if not samples:
        return [0.0] * n_bands
    arr = np.array(samples, dtype="float32")
    n = min(8192, len(arr))
    spectrum = np.abs(np.fft.rfft(arr[:n]))
    bands = np.array_split(spectrum, n_bands)
    return [float(math.log1p(b.sum())) for b in bands]


def features_from_pcm(pcm: bytes, sample_rate: int) -> list[float]:
    samples = _pcm16_to_float(pcm)
    if not samples:
        return [0.0] * _FEATURE_DIM
    f0 = _autocorr_f0(samples, sample_rate) / 400.0
    zcr = _zero_crossing_rate(samples)
    centroid = _spectral_centroid_simple(samples, sample_rate) / (sample_rate / 2)
    rms = min(1.0, _rms(samples) * 4)
    bands = _band_energies(samples, sample_rate, n_bands=4)
    band_max = max(bands) if bands else 1.0
    bands_n = [b / band_max if band_max > 0 else 0.0 for b in bands]
    vec = [f0, zcr, centroid, rms] + bands_n
    return vec[:_FEATURE_DIM] + [0.0] * (_FEATURE_DIM - len(vec))


def cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------- #
# Multi-user enrollment + matching
# --------------------------------------------------------------------------- #


def _get_user_entry(state: dict, user_id: str) -> dict:
    users = state.setdefault("users", {})
    entry = users.get(user_id)
    if not entry:
        entry = {"voiceprint": None, "count": 0}
        users[user_id] = entry
    return entry


def enroll_user(user_id: str, pcm: bytes, sample_rate: int) -> dict:
    """Enroll or update a specific user's voiceprint."""
    state = _load_state()
    entry = _get_user_entry(state, user_id)
    features = features_from_pcm(pcm, sample_rate)
    vp = entry.get("voiceprint")
    count = int(entry.get("count") or 0)
    if not vp:
        entry["voiceprint"] = features
        entry["count"] = 1
    elif count < _ENROLL_FRAMES:
        merged = [(a * count + b) / (count + 1) for a, b in zip(vp, features)]
        entry["voiceprint"] = merged
        entry["count"] = count + 1
    else:
        # Slow rolling average after enrollment completes.
        merged = [a * 0.92 + b * 0.08 for a, b in zip(vp, features)]
        entry["voiceprint"] = merged
    _save_state(state)
    return {"user_id": user_id, "enrolled": count < _ENROLL_FRAMES, "count": entry["count"]}


def enroll_active_user(pcm: bytes, sample_rate: int) -> dict:
    return enroll_user(_active_user_id(), pcm, sample_rate)


def match_speaker(pcm: bytes, sample_rate: int, *, threshold: Optional[float] = None) -> dict:
    """
    Compare utterance against all enrolled users. Returns best match::

        {user_id, similarity, enrolled, known}
    """
    threshold = _DEFAULT_THRESHOLD if threshold is None else threshold
    features = features_from_pcm(pcm, sample_rate)
    state = _load_state()
    users = state.get("users") or {}
    best_uid = ""
    best_sim = 0.0
    for uid, entry in users.items():
        vp = entry.get("voiceprint")
        if not vp:
            continue
        sim = cosine_sim(vp, features)
        if sim > best_sim:
            best_sim = sim
            best_uid = uid
    enrolled = bool(best_uid) and int((users.get(best_uid) or {}).get("count") or 0) < _ENROLL_FRAMES
    known = best_sim >= threshold
    return {
        "user_id": best_uid or _active_user_id(),
        "similarity": best_sim,
        "enrolled": enrolled,
        "known": known,
    }


def reset_voiceprint(user_id: Optional[str] = None) -> None:
    state = _load_state()
    if user_id:
        users = state.setdefault("users", {})
        users.pop(user_id, None)
    else:
        state["users"] = {}
    _save_state(state)


# --------------------------------------------------------------------------- #
# Backwards-compatible single-user API
# --------------------------------------------------------------------------- #


def enroll_or_match(pcm: bytes, sample_rate: int) -> dict:
    uid = _active_user_id()
    match = match_speaker(pcm, sample_rate)
    enroll = enroll_user(uid, pcm, sample_rate)
    return {
        "enrolled": enroll.get("enrolled", False),
        "similarity": match.get("similarity", 0.0),
        "speaker": match.get("user_id") or uid,
    }


def is_known_speaker(pcm: bytes, sample_rate: int, *, threshold: float = 0.85) -> bool:
    res = match_speaker(pcm, sample_rate, threshold=threshold)
    if res.get("enrolled"):
        return True
    return bool(res.get("known"))


__all__ = [
    "cosine_sim",
    "enroll_active_user",
    "enroll_or_match",
    "enroll_user",
    "features_from_pcm",
    "is_known_speaker",
    "match_speaker",
    "reset_voiceprint",
]
