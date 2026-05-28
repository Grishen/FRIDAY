"""Extended vision Q&A session — keep discussing the same image without re-capture."""

from __future__ import annotations

import os
import time
from typing import Optional

_SESSION: dict = {"active": False, "expires_at": 0.0, "path": "", "kind": ""}


def _default_minutes() -> float:
    try:
        return max(1.0, float(os.environ.get("JARVIS_VISION_SESSION_MIN", "10")))
    except (TypeError, ValueError):
        return 10.0


def start_vision_session(*, minutes: Optional[float] = None) -> str:
    from vision import get_last_image

    path, kind = get_last_image()
    if not path:
        return "I don't have an image to stay on yet — show me one first."
    mins = minutes if minutes is not None else _default_minutes()
    _SESSION["active"] = True
    _SESSION["expires_at"] = time.time() + mins * 60
    _SESSION["path"] = path
    _SESSION["kind"] = kind
    return f"Vision session started — I'll keep referring to that image for {int(mins)} minutes."


def end_vision_session() -> str:
    _SESSION["active"] = False
    _SESSION["expires_at"] = 0.0
    _SESSION["path"] = ""
    return "Vision session ended."


def is_active() -> bool:
    if not _SESSION.get("active"):
        return False
    if time.time() > float(_SESSION.get("expires_at") or 0):
        _SESSION["active"] = False
        return False
    return bool(_SESSION.get("path"))


def session_ask(prompt: str) -> str:
    if not is_active():
        return end_vision_session() + " Ask again after showing me a new image."
    from vision import analyze_image

    path = str(_SESSION.get("path") or "")
    res = analyze_image(path, prompt=prompt or "Tell me more about this image.", history_kind="vision_session")
    return res.get("text") or res.get("error") or "I couldn't analyze that image."


def describe_session() -> str:
    if not is_active():
        return "No active vision session."
    remaining = max(0, int((float(_SESSION["expires_at"]) - time.time()) / 60))
    return f"Vision session active on {_SESSION.get('kind', 'image')} — about {remaining} minutes left."


__all__ = [
    "describe_session",
    "end_vision_session",
    "is_active",
    "session_ask",
    "start_vision_session",
]
