"""Lightweight sentiment detection + persona adaptation.

Two backends:

1. **LLM** (preferred when ``OPENAI_API_KEY`` is set) — fast, robust, returns
   a structured label + valence number.
2. **Lexicon** fallback — small positive/negative word list, good enough to
   detect "rough day" tone without any external call.

Detected moods are persisted as durable ``mood:`` notes in episodic memory so
they accumulate over time. The brain context builder reads recent moods to
let the persona adapt empathetically.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

_POS = {
    "great", "good", "amazing", "awesome", "happy", "love", "loved", "love it",
    "excited", "fun", "fantastic", "wonderful", "nice", "calm", "grateful",
    "yay", "lol", "lmao",
}
_NEG = {
    "bad", "sad", "tired", "exhausted", "depressed", "angry", "annoyed",
    "frustrated", "stressed", "anxious", "worried", "lonely", "hate",
    "awful", "terrible", "horrible", "sucks", "miserable", "broken", "hurt",
    "ugh", "crying", "burnout",
}

_LABEL_FROM_VALENCE = (
    (-0.66, "distressed"),
    (-0.25, "down"),
    (0.25, "neutral"),
    (0.66, "positive"),
    (1.0, "happy"),
)


def _label_for_valence(v: float) -> str:
    for threshold, label in _LABEL_FROM_VALENCE:
        if v <= threshold:
            return label
    return "happy"


def _token_pass(text: str) -> tuple[float, str]:
    tokens = re.findall(r"[a-zA-Z']+", (text or "").lower())
    pos = sum(1 for t in tokens if t in _POS)
    neg = sum(1 for t in tokens if t in _NEG)
    if pos == 0 and neg == 0:
        return 0.0, "neutral"
    valence = (pos - neg) / max(1, pos + neg)
    return float(valence), _label_for_valence(valence)


def _llm_sentiment(text: str) -> Optional[tuple[float, str]]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    try:
        client = OpenAI(api_key=key)
        model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a sentiment classifier. Read the user message and respond "
                        "with ONLY a strict JSON object: "
                        '{"valence": float in [-1,1], "label": "happy|positive|neutral|down|distressed"}. '
                        "No prose."
                    ),
                },
                {"role": "user", "content": text[:1200]},
            ],
            temperature=0.0,
        )
        content = getattr(completion.choices[0].message, "content", None) or ""
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        v = float(data.get("valence", 0.0))
        v = max(-1.0, min(1.0, v))
        lbl = str(data.get("label") or _label_for_valence(v)).lower().strip()
        if lbl not in {"happy", "positive", "neutral", "down", "distressed"}:
            lbl = _label_for_valence(v)
        return v, lbl
    except Exception:
        return None


def detect_sentiment(text: str) -> dict[str, object]:
    """Return ``{"valence": float, "label": str, "source": str}``."""
    txt = (text or "").strip()
    if not txt:
        return {"valence": 0.0, "label": "neutral", "source": "empty"}
    llm = _llm_sentiment(txt)
    if llm is not None:
        v, lbl = llm
        return {"valence": v, "label": lbl, "source": "llm"}
    v, lbl = _token_pass(txt)
    return {"valence": v, "label": lbl, "source": "lexicon"}


def record_user_mood(text: str) -> dict[str, object]:
    """Detect mood for an utterance and store it as a durable memory note."""
    sentiment = detect_sentiment(text)
    label = str(sentiment.get("label", "neutral"))
    if label == "neutral":
        return sentiment
    try:
        from memory.episodic_memory import memory_append_turn

        valence = float(sentiment.get("valence", 0.0))
        memory_append_turn("note", f"mood:{label} (valence={valence:+.2f}) from: {text[:160]}")
    except Exception:
        pass
    return sentiment


def recent_mood_label(*, max_rows: int = 60) -> Optional[str]:
    """Return the most recent mood label, or None if none recorded yet."""
    try:
        from memory.episodic_memory import memory_recent_rows
    except Exception:
        return None
    rows = memory_recent_rows(limit=max_rows)
    for role, content in reversed(rows):
        if role != "note":
            continue
        c = (content or "").strip().lower()
        if c.startswith("mood:"):
            m = re.match(r"mood:([a-z]+)", c)
            if m:
                return m.group(1)
    return None


def persona_mood_overlay(mood: Optional[str]) -> str:
    """Return a small system-prompt addition tuned to current mood."""
    if not mood or mood == "neutral":
        return ""
    if mood == "distressed":
        return (
            "\nThe user appears distressed right now. Lead with warmth and brevity; "
            "acknowledge feelings before offering solutions; avoid jokes; ask before "
            "running multi-step tools."
        )
    if mood == "down":
        return (
            "\nThe user seems a bit low. Soften your tone, keep replies short and "
            "supportive, and offer concrete help in a gentle way."
        )
    if mood == "happy":
        return (
            "\nThe user seems upbeat. Match their energy lightly; a small touch of "
            "warmth or wit is welcome."
        )
    if mood == "positive":
        return "\nThe user is in a good mood. Stay friendly and engaged."
    return ""


__all__ = [
    "detect_sentiment",
    "persona_mood_overlay",
    "recent_mood_label",
    "record_user_mood",
]
