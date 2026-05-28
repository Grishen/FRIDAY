"""Mood trajectory across sessions + adaptive persona hints."""

from __future__ import annotations

import os
import re
from typing import Optional


def _recent_moods(*, max_items: int = 12) -> list[tuple[str, float]]:
    try:
        from memory.episodic_memory import memory_recent_rows
    except Exception:
        return []
    out: list[tuple[str, float]] = []
    try:
        rows = memory_recent_rows(limit=200)
    except Exception:
        return []
    for role, content in reversed(rows):
        if role != "note":
            continue
        c = (content or "").strip()
        if not c.lower().startswith("mood:"):
            continue
        m = re.search(r"mood:([a-z]+)", c, re.I)
        v = re.search(r"valence=([+-]?\d+\.?\d*)", c)
        if m:
            label = m.group(1).lower()
            val = float(v.group(1)) if v else 0.0
            out.append((label, val))
        if len(out) >= max_items:
            break
    return list(reversed(out))


def mood_trajectory_summary() -> str:
    moods = _recent_moods(max_items=8)
    if len(moods) < 3:
        return ""
    labels = [m[0] for m in moods]
    negatives = sum(1 for l in labels if l in ("distressed", "down"))
    positives = sum(1 for l in labels if l in ("happy", "positive"))
    if negatives >= 3 and negatives > positives:
        return "You've sounded low several times recently — I'll keep responses steady and supportive."
    if positives >= 4 and positives > negatives:
        return "You've been in good spirits lately."
    recent_three = labels[-3:]
    if all(l in ("distressed", "down") for l in recent_three):
        return "The last few conversations felt heavy — I'm here if you want to talk it through."
    return ""


def suggest_persona_switch() -> Optional[str]:
    if os.environ.get("JARVIS_MOOD_PERSONA", "0").strip().lower() not in (
        "1", "true", "yes", "on",
    ):
        return None

    moods = _recent_moods(max_items=5)
    if not moods:
        return None
    recent = [m[0] for m in moods[-3:]]
    distressed = sum(1 for l in recent if l in ("distressed", "down"))
    upbeat = sum(1 for l in recent if l in ("happy", "positive"))

    try:
        from personas import get_persona_key

        current = get_persona_key()
    except Exception:
        current = "friday"

    if distressed >= 2 and current not in ("therapist", "companion"):
        return "therapist"
    if upbeat >= 2 and current not in ("coach", "companion"):
        return "coach"
    return None


def should_suppress_cheerful_filler() -> bool:
    moods = _recent_moods(max_items=4)
    if not moods:
        return False
    recent = [m[0] for m in moods[-2:]]
    return all(l in ("distressed", "down") for l in recent)


def trajectory_for_prompt() -> str:
    return mood_trajectory_summary()


__all__ = [
    "mood_trajectory_summary",
    "should_suppress_cheerful_filler",
    "suggest_persona_switch",
    "trajectory_for_prompt",
]
