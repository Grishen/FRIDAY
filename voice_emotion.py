"""Map detected user mood + active persona → ElevenLabs voice settings.

The streaming TTS already pulls voice settings from the active persona. This
module overlays a *mood-driven* adjustment so the assistant's voice softens
when you sound stressed, brightens when you sound cheerful, etc.

It does NOT modify env vars; it returns a dict that the TTS layer can read
each time it speaks (via :func:`current_voice_settings`).
"""

from __future__ import annotations

import os
import time
from typing import Optional


_LAST_SETTINGS: dict = {}
_LAST_SETTINGS_AT: float = 0.0
_TTL_S: float = 60.0


def _recent_mood() -> str:
    """Most-recent mood label from sentiment (positive|negative|neutral|None)."""
    try:
        from sentiment import recent_mood_label

        return (recent_mood_label() or "neutral").lower()
    except Exception:
        return "neutral"


def _persona_voice() -> dict:
    try:
        from personas import get_persona

        return dict(get_persona().get("voice") or {})
    except Exception:
        return {}


_MOOD_OVERLAYS = {
    "positive": {"stability_delta": -0.05, "style_delta": +0.10, "rate": "+5%"},
    "negative": {"stability_delta": +0.15, "style_delta": -0.15, "rate": "-5%"},
    "stressed": {"stability_delta": +0.20, "style_delta": -0.20, "rate": "-8%"},
    "calm":     {"stability_delta": +0.05, "style_delta": +0.00, "rate": "+0%"},
    "neutral":  {"stability_delta": 0.0,    "style_delta": 0.0,   "rate": "+0%"},
}


def compute_voice_settings(mood: Optional[str] = None) -> dict:
    base = _persona_voice()
    mood = (mood or _recent_mood() or "neutral").lower()
    overlay = _MOOD_OVERLAYS.get(mood, _MOOD_OVERLAYS["neutral"])
    out: dict = dict(base)

    if "stability" in out:
        try:
            out["stability"] = max(0.0, min(1.0, float(out["stability"]) + overlay["stability_delta"]))
        except (TypeError, ValueError):
            pass
    if "style" in out:
        try:
            out["style"] = max(0.0, min(1.0, float(out["style"]) + overlay["style_delta"]))
        except (TypeError, ValueError):
            pass
    out["rate"] = overlay["rate"]
    out["mood"] = mood
    return out


def current_voice_settings(*, refresh: bool = False) -> dict:
    """Return cached voice settings; refresh every TTL_S seconds."""
    global _LAST_SETTINGS, _LAST_SETTINGS_AT
    now = time.time()
    if refresh or not _LAST_SETTINGS or (now - _LAST_SETTINGS_AT) > _TTL_S:
        _LAST_SETTINGS = compute_voice_settings()
        _LAST_SETTINGS_AT = now
    return _LAST_SETTINGS


def describe_voice_state() -> str:
    s = current_voice_settings(refresh=True)
    if not s:
        return "No voice settings available."
    bits = []
    for k in ("mood", "stability", "style", "similarity", "speaker_boost", "rate"):
        if k in s:
            bits.append(f"{k}={s[k]}")
    return ", ".join(bits)


__all__ = ["compute_voice_settings", "current_voice_settings", "describe_voice_state"]
