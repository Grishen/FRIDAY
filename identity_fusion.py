"""Face + voice identity fusion for multi-user auto-switching.

Voiceprints (:mod:`speaker_id`) are primary. Optional face thumbnails per user
(:func:`enroll_active_user_face`) disambiguate when voice confidence is weak or
when the speaker is unknown.

Storage: ``data/jarvis_faceprints.json`` + ``data/face_thumbs/<user>.jpg``
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()
_THUMB_SIZE = 64


def _data_dir() -> Path:
    base = Path(os.environ.get("JARVIS_DATA_DIR", "data"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _state_path() -> Path:
    return _data_dir() / "jarvis_faceprints.json"


def _thumb_dir() -> Path:
    d = _data_dir() / "face_thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _face_enabled() -> bool:
    return os.environ.get("JARVIS_FACE_ID", "0").strip().lower() in (
        "1", "true", "yes", "on", "auto",
    )


def _load_state() -> dict:
    path = _state_path()
    if not path.is_file():
        return {"users": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"users": {}}
    if "users" not in raw:
        raw["users"] = {}
    return raw


def _save_state(state: dict) -> None:
    try:
        _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _active_user_id() -> str:
    try:
        from user_profiles import active_user

        return active_user() or "default"
    except Exception:
        return "default"


def _thumb_features(path: str) -> Optional[list[float]]:
    try:
        from PIL import Image  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return None
    try:
        img = Image.open(path).convert("RGB")
        img = img.resize((_THUMB_SIZE, _THUMB_SIZE))
        arr = np.asarray(img, dtype="float32") / 255.0
        # Simple RGB histogram bins (8 per channel → 24 dims).
        feats: list[float] = []
        for ch in range(3):
            hist, _ = np.histogram(arr[:, :, ch], bins=8, range=(0.0, 1.0))
            total = float(hist.sum()) or 1.0
            feats.extend((hist / total).tolist())
        return feats
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def enroll_active_user_face() -> str:
    """Capture webcam thumbnail for the active user."""
    if not _face_enabled():
        return "Face ID is off. Set JARVIS_FACE_ID=1 first."
    try:
        from vision import capture_webcam
    except Exception:
        return "Vision module unavailable."

    ok, path = capture_webcam()
    if not ok or not path:
        return path or "Couldn't capture a face image."

    feats = _thumb_features(path)
    if not feats:
        return "Install Pillow + numpy to enroll face prints."

    uid = _active_user_id()
    thumb_dest = _thumb_dir() / f"{uid}.jpg"
    try:
        import shutil

        shutil.copy2(path, thumb_dest)
    except Exception:
        thumb_dest = Path(path)

    with _LOCK:
        state = _load_state()
        state["users"][uid] = {
            "thumb": str(thumb_dest),
            "features": feats,
        }
        _save_state(state)
    return f"Face enrolled for {uid}."


def match_face_user(*, threshold: float = 0.88) -> dict:
    """Return best face match: {user_id, similarity, known}."""
    if not _face_enabled():
        return {"user_id": "", "similarity": 0.0, "known": False}
    try:
        from vision import capture_webcam
    except Exception:
        return {"user_id": "", "similarity": 0.0, "known": False}

    ok, path = capture_webcam()
    if not ok or not path:
        return {"user_id": "", "similarity": 0.0, "known": False}

    probe = _thumb_features(path)
    if not probe:
        return {"user_id": "", "similarity": 0.0, "known": False}

    state = _load_state()
    best_uid = ""
    best_sim = 0.0
    for uid, entry in (state.get("users") or {}).items():
        feats = entry.get("features")
        if not isinstance(feats, list):
            continue
        sim = _cosine(probe, feats)
        if sim > best_sim:
            best_sim = sim
            best_uid = uid

    known = best_sim >= threshold and bool(best_uid)
    return {"user_id": best_uid if known else "", "similarity": best_sim, "known": known}


def fuse_identity(pcm: bytes, sample_rate: int) -> dict:
    """
    Combine voice + optional face signals.

    Returns ``{user_id, source, voice_sim, face_sim, switched}``.
    """
    out = {
        "user_id": "",
        "source": "",
        "voice_sim": 0.0,
        "face_sim": 0.0,
        "switched": False,
    }
    if not pcm or not sample_rate:
        return out

    try:
        from speaker_id import enroll_active_user, match_speaker
        from user_profiles import active_user, set_active_user
    except Exception:
        return out

    voice = match_speaker(pcm, int(sample_rate))
    enroll_active_user(pcm, int(sample_rate))
    out["voice_sim"] = float(voice.get("similarity") or 0.0)

    try:
        v_thresh = float(os.environ.get("JARVIS_SPEAKER_THRESHOLD", "0.82"))
    except (TypeError, ValueError):
        v_thresh = 0.82

    uid = ""
    source = ""
    if voice.get("known") and not voice.get("enrolled"):
        uid = str(voice.get("user_id") or "")
        source = "voice"

    face_flag = os.environ.get("JARVIS_FACE_ID", "0").strip().lower()
    use_face = face_flag in ("1", "true", "yes", "on", "auto")
    if use_face and (not uid or out["voice_sim"] < v_thresh):
        try:
            f_thresh = float(os.environ.get("JARVIS_FACE_THRESHOLD", "0.88"))
        except (TypeError, ValueError):
            f_thresh = 0.88
        face = match_face_user(threshold=f_thresh)
        out["face_sim"] = float(face.get("similarity") or 0.0)
        if face.get("known"):
            f_uid = str(face.get("user_id") or "")
            if not uid:
                uid = f_uid
                source = "face"
            elif uid == f_uid:
                source = "voice+face"
            elif out["face_sim"] > out["voice_sim"]:
                uid = f_uid
                source = "face_override"

    if not uid:
        return out

    current = active_user()
    out["user_id"] = uid
    out["source"] = source
    if uid != current:
        set_active_user(uid, display_name=uid)
        out["switched"] = True
    return out


__all__ = [
    "enroll_active_user_face",
    "fuse_identity",
    "match_face_user",
]
