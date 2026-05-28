"""Learn from explicit user feedback during a session.

Handles:
- "That was too long" → terse verbosity
- "Don't interrupt me" → disable backchannels for session
- "You got that wrong" → correction note in memory
- "Be more detailed" → rich verbosity
"""

from __future__ import annotations

import os
import re
from typing import Optional

_SESSION_FLAGS: dict[str, bool] = {"backchannel": True}


def session_backchannel_enabled() -> bool:
    return _SESSION_FLAGS.get("backchannel", True)


def disable_backchannel_for_session() -> None:
    _SESSION_FLAGS["backchannel"] = False
    os.environ["JARVIS_BACKCHANNEL"] = "0"


def _addr() -> str:
    try:
        from personas import get_address

        a = get_address()
        return f", {a}" if a else ""
    except Exception:
        return ""


_TOO_LONG = re.compile(
    r"\b(too long|shorter|be brief|keep it short|tldr|get to the point|"
    r"that was long|way too much)\b",
    re.I,
)
_TOO_SHORT = re.compile(
    r"\b(more detail|go deeper|explain more|tell me more|expand on|"
    r"that was too short|not enough detail)\b",
    re.I,
)
_NO_INTERRUPT = re.compile(
    r"\b(don'?t interrupt|stop interrupting|no backchannel|let me finish|"
    r"don'?t talk over me)\b",
    re.I,
)
_WRONG = re.compile(
    r"\b(you got that wrong|that'?s wrong|that is wrong|incorrect|"
    r"not what i said|you misunderstood|that'?s not right)\b",
    re.I,
)


def try_handle_feedback(text: str) -> Optional[str]:
    """
    If ``text`` is explicit feedback, apply learning and return a speakable reply.
    """
    t = (text or "").strip()
    if not t:
        return None
    low = t.lower()

    if _NO_INTERRUPT.search(low):
        disable_backchannel_for_session()
        return f"Understood — I won't chime in while you're speaking{_addr()}."

    if _TOO_LONG.search(low):
        try:
            from personas import set_verbosity

            set_verbosity("terse")
        except Exception:
            pass
        try:
            from relationship_memory import persist_trait

            persist_trait("prefers brief answers after feedback")
        except Exception:
            pass
        return f"Got it — I'll keep it shorter{_addr()}."

    if _TOO_SHORT.search(low):
        try:
            from personas import set_verbosity

            set_verbosity("rich")
        except Exception:
            pass
        return f"I'll go deeper next time{_addr()}."

    if _WRONG.search(low):
        try:
            from memory.episodic_memory import memory_append_turn

            memory_append_turn(
                "note",
                f"correction: user flagged last answer as wrong — context: {t[:200]}",
            )
        except Exception:
            pass
        return f"Thanks for the correction — I'll adjust{_addr()}. What should I fix?"

    return None


__all__ = [
    "disable_backchannel_for_session",
    "session_backchannel_enabled",
    "try_handle_feedback",
]
