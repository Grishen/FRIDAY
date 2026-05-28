"""Derived relationship traits — soft patterns about how the user interacts.

Observes turn timing, mood, verbosity feedback, and recurring topics, then
persists durable ``trait:`` notes in episodic memory for richer context.

Traits are heuristic, not ground truth — the brain treats them as hints.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import time
from collections import Counter
from typing import Optional

_TRAIT_PREFIX = "trait:"
_OBS_LOCK = __import__("threading").Lock()
_HOUR_BUCKETS: Counter = Counter()
_RECENT_TOPICS: list[str] = []
_LAST_OBSERVE_AT: float = 0.0

_TERSE_FEEDBACK = re.compile(
    r"\b(too long|shorter|be brief|keep it short|tldr|get to the point)\b", re.I
)
_RICH_FEEDBACK = re.compile(
    r"\b(more detail|go deeper|explain more|tell me more|expand on)\b", re.I
)
_WORK_APPS = re.compile(
    r"\b(xcode|visual studio|code|terminal|slack|figma|notion|excel|word)\b", re.I
)


def _enabled() -> bool:
    return os.environ.get("JARVIS_RELATIONSHIP_MEMORY", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def observe_turn(utterance: str, *, mood: Optional[str] = None) -> None:
    """Record lightweight signals from one user turn (in-process counters)."""
    if not _enabled():
        return
    text = (utterance or "").strip()
    if not text or text == "none":
        return

    global _LAST_OBSERVE_AT
    with _OBS_LOCK:
        hour = _dt.datetime.now().hour
        if 5 <= hour < 12:
            _HOUR_BUCKETS["morning"] += 1
        elif 12 <= hour < 17:
            _HOUR_BUCKETS["afternoon"] += 1
        elif 17 <= hour < 22:
            _HOUR_BUCKETS["evening"] += 1
        else:
            _HOUR_BUCKETS["late_night"] += 1

        if _TERSE_FEEDBACK.search(text):
            _persist_trait("prefers brief answers when asked for shorter replies")
        if _RICH_FEEDBACK.search(text):
            _persist_trait("appreciates richer detail when asked to go deeper")

        if mood and mood in ("stressed", "distressed", "negative", "anxious"):
            _persist_trait("may prefer calm, steady responses when mood is low")

        try:
            from topic_threads import observe_utterance as _obs_threads  # noqa: F401 — side effect
        except Exception:
            pass

        _LAST_OBSERVE_AT = time.time()

    maybe_refresh_traits()


def _persist_trait(text: str) -> None:
    note = f"{_TRAIT_PREFIX}{text.strip()}"
    if not note.strip() or note == _TRAIT_PREFIX:
        return
    try:
        from memory.episodic_memory import memory_recent_rows, memory_append_turn

        recent = memory_recent_rows(limit=80)
        for role, content in recent:
            if role == "note" and (content or "").strip().lower() == note.lower():
                return
        memory_append_turn("note", note)
    except Exception:
        pass


def derive_traits() -> list[str]:
    """Compute trait strings from in-process counters + recent memory."""
    traits: list[str] = []

    with _OBS_LOCK:
        total = sum(_HOUR_BUCKETS.values()) or 1
        for bucket, count in _HOUR_BUCKETS.most_common(2):
            if count / total >= 0.45:
                if bucket == "late_night":
                    traits.append("often talks late at night")
                elif bucket == "morning":
                    traits.append("often starts conversations in the morning")
                elif bucket == "evening":
                    traits.append("often active in the evening")

    try:
        from sentiment import recent_mood_label

        mood = (recent_mood_label() or "").lower()
        if mood in ("stressed", "distressed", "negative"):
            traits.append("recent mood has been heavy — lead with empathy")
    except Exception:
        pass

    try:
        from personas import get_verbosity

        v = get_verbosity()
        if v == "terse":
            traits.append("prefers terse replies")
        elif v == "rich":
            traits.append("prefers detailed replies")
    except Exception:
        pass

    return traits[:6]


def maybe_refresh_traits(*, min_interval_s: float = 900.0) -> None:
    """Persist derived traits at most every ``min_interval_s`` seconds."""
    if not _enabled():
        return
    global _LAST_OBSERVE_AT
    if (time.time() - _LAST_OBSERVE_AT) < 5:
        return
    for t in derive_traits():
        _persist_trait(t)


def list_traits(*, max_items: int = 8) -> list[str]:
    try:
        from memory.episodic_memory import memory_recent_rows

        rows = memory_recent_rows(limit=300)
    except Exception:
        return []
    out: list[str] = []
    for role, content in rows:
        if role != "note":
            continue
        c = (content or "").strip()
        if c.lower().startswith(_TRAIT_PREFIX):
            out.append(c[len(_TRAIT_PREFIX):].strip())
    # dedupe preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    return deduped[-max_items:]


def traits_for_prompt() -> str:
    traits = list_traits(max_items=5)
    derived = derive_traits()
    merged: list[str] = []
    seen: set[str] = set()
    for t in traits + derived:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        merged.append(t)
    if not merged:
        return ""
    return "Relationship traits (soft hints): " + "; ".join(merged[:6])


def persist_trait(text: str) -> None:
    """Public wrapper to store a relationship trait note."""
    _persist_trait(text)


__all__ = [
    "derive_traits",
    "list_traits",
    "maybe_refresh_traits",
    "observe_turn",
    "persist_trait",
    "traits_for_prompt",
]
