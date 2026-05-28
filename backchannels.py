"""Light backchannels while the user is still talking.

When someone speaks at length, a human listener often murmurs "mm-hmm",
"right", or "got it" without taking the floor. This module supplies short,
persona-aware acknowledgments during long utterances captured by VAD.

Enable with ``JARVIS_BACKCHANNEL=1``. Disabled by default because speaker
playback can leak into the mic on some setups — use headphones for best results.
"""

from __future__ import annotations

import os
import random
import threading
import time

_BACKCHANNEL_LOCK = threading.Lock()
_LAST_AT: float = 0.0
_SPOKEN_THIS_UTTERANCE = False


def enabled() -> bool:
    return os.environ.get("JARVIS_BACKCHANNEL", "0").strip().lower() in ("1", "true", "yes", "on")


def _min_gap_s() -> float:
    try:
        return max(2.0, float(os.environ.get("JARVIS_BACKCHANNEL_GAP", "8")))
    except (TypeError, ValueError):
        return 8.0


def _trigger_after_s() -> float:
    try:
        return max(2.0, float(os.environ.get("JARVIS_BACKCHANNEL_AFTER", "4")))
    except (TypeError, ValueError):
        return 4.0


def reset_utterance() -> None:
    global _SPOKEN_THIS_UTTERANCE
    _SPOKEN_THIS_UTTERANCE = False


def _phrases() -> list[str]:
    try:
        from personas import get_persona

        p = get_persona()
        custom = p.get("backchannel_phrases")
        if isinstance(custom, list) and custom:
            return [str(x) for x in custom]
        tone = (p.get("tone") or "").lower()
        if tone == "formal":
            return ["Mm.", "I see.", "Understood.", "Right."]
        if tone == "gentle":
            return ["Mm.", "I hear you.", "Yes.", "Go on."]
        if tone == "energetic":
            return ["Got it.", "Yep.", "Right.", "Uh-huh."]
        if tone == "warm":
            return ["Mm-hmm.", "Sure.", "Right.", "Okay."]
    except Exception:
        pass
    return ["Mm-hmm.", "Right.", "Got it.", "I see."]


def maybe_backchannel(elapsed_s: float, *, speak_fn) -> bool:
    """
    Fire at most one backchannel per utterance when ``elapsed_s`` exceeds the
    trigger threshold. Returns True if a backchannel was dispatched.
    """
    global _SPOKEN_THIS_UTTERANCE, _LAST_AT
    if not enabled() or _SPOKEN_THIS_UTTERANCE:
        return False
    try:
        from feedback_learning import session_backchannel_enabled

        if not session_backchannel_enabled():
            return False
    except Exception:
        pass
    if elapsed_s < _trigger_after_s():
        return False
    now = time.time()
    if (now - _LAST_AT) < _min_gap_s():
        return False

    phrase = random.choice(_phrases())
    with _BACKCHANNEL_LOCK:
        if _SPOKEN_THIS_UTTERANCE:
            return False
        _SPOKEN_THIS_UTTERANCE = True
        _LAST_AT = now

    def _run() -> None:
        try:
            speak_fn(phrase)
        except Exception:
            pass

    threading.Thread(target=_run, name="backchannel", daemon=True).start()
    return True


__all__ = ["enabled", "maybe_backchannel", "reset_utterance"]
