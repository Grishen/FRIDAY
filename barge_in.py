"""Classify user speech that arrives while the assistant is still talking.

When the user barges in, the raw transcript may mean different things:

- **stop**      — hard interrupt ("stop", "wait", "be quiet")
- **correction** — amend the previous request ("actually Tuesday", "no I meant email")
- **new_topic**  — abandon the current thread ("never mind", "forget that", "new question")
- **none**       — normal utterance (or not an interrupt context)
"""

from __future__ import annotations

import re

_STOP_RE = re.compile(
    r"^(?:stop|wait|hold on|hang on|quiet|be quiet|shush|silence|"
    r"stop talking|stop speaking|that's enough|enough)\b",
    re.I,
)

_CORRECTION_RE = re.compile(
    r"\b(actually|no wait|wait no|i meant|i mean|correction|"
    r"not that|instead|rather|change that to|make it|switch it to)\b",
    re.I,
)

_NEW_TOPIC_RE = re.compile(
    r"\b(never mind|nevermind|forget that|forget it|skip that|"
    r"new question|different question|something else|start over|"
    r"cancel that|drop that)\b",
    re.I,
)

_LEAD_STRIP_RE = re.compile(
    r"^(?:actually|no wait|wait no|i meant|i mean|correction|"
    r"not that|instead|rather|change that to|make it|switch it to)\s*",
    re.I,
)


def classify_interrupt(text: str, *, was_speaking: bool = False) -> str:
    """
    Return one of: ``stop``, ``correction``, ``new_topic``, ``none``.

    Only meaningful when ``was_speaking`` is True (user spoke over the assistant).
    """
    if not was_speaking:
        return "none"
    t = (text or "").strip()
    if not t:
        return "none"
    if _STOP_RE.search(t):
        return "stop"
    if _NEW_TOPIC_RE.search(t):
        return "new_topic"
    if _CORRECTION_RE.search(t):
        return "correction"
    return "none"


def extract_correction(text: str) -> str:
    """Strip leading correction phrases so slot-fillers get the payload."""
    t = (text or "").strip()
    prev = None
    while prev != t:
        prev = t
        t = _LEAD_STRIP_RE.sub("", t).strip(" ,.")
    return t


__all__ = ["classify_interrupt", "extract_correction"]
