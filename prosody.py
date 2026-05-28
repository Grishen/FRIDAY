"""Content-aware prosody hints for streaming TTS.

Adjusts ElevenLabs voice settings per sentence/chunk based on punctuation,
length, and emotional cues. Composes on top of persona defaults and
:mod:`voice_emotion` mood overlays.
"""

from __future__ import annotations

import re
from typing import Optional

_NEG_RE = re.compile(
    r"\b(sorry|unfortunately|failed|error|couldn't|can't|cannot|problem|issue|"
    r"wrong|mistake|bad news|didn't work)\b",
    re.I,
)
_POS_RE = re.compile(
    r"\b(great|perfect|done|success|completed|wonderful|excellent|nice|good news)\b",
    re.I,
)
_LIST_RE = re.compile(r"^\s*(\d+[\.\)]|[-•*])\s+")


def _merge_settings(base: dict, *, stability_delta: float = 0.0,
                    style_delta: float = 0.0) -> dict:
    out = dict(base or {})
    if "stability" in out:
        try:
            out["stability"] = max(0.0, min(1.0, float(out["stability"]) + stability_delta))
        except (TypeError, ValueError):
            pass
    if "style" in out:
        try:
            out["style"] = max(0.0, min(1.0, float(out["style"]) + style_delta))
        except (TypeError, ValueError):
            pass
    return out


def pause_after_chunk(text: str) -> float:
    """Seconds to pause after this chunk (lists / long sentences)."""
    t = (text or "").strip()
    if not t:
        return 0.0
    if _LIST_RE.match(t):
        return 0.18
    if t.endswith((":", ";")):
        return 0.12
    if len(t) > 180:
        return 0.08
    return 0.0


def voice_settings_for_chunk(text: str, base: Optional[dict] = None) -> dict:
    """
    Return ElevenLabs-style voice_settings dict for a single spoken chunk.
    """
    try:
        from voice_emotion import current_voice_settings

        settings = dict(base or current_voice_settings() or {})
    except Exception:
        settings = dict(base or {})

    t = (text or "").strip()
    if not t:
        return settings

    # Short punchy lines — slightly livelier.
    if len(t) < 48 and not t.endswith("?"):
        settings = _merge_settings(settings, stability_delta=-0.06, style_delta=+0.05)

    # Questions — brighter delivery.
    if t.endswith("?"):
        settings = _merge_settings(settings, stability_delta=-0.04, style_delta=+0.08)

    # Bad news — slower, steadier.
    if _NEG_RE.search(t):
        settings = _merge_settings(settings, stability_delta=+0.12, style_delta=-0.10)

    # Good news — warmer.
    if _POS_RE.search(t):
        settings = _merge_settings(settings, stability_delta=-0.03, style_delta=+0.06)

    # Long explanatory sentences — calm and measured.
    if len(t) > 160 and not t.endswith("?"):
        settings = _merge_settings(settings, stability_delta=+0.06, style_delta=-0.04)

    return settings


__all__ = ["pause_after_chunk", "voice_settings_for_chunk"]
