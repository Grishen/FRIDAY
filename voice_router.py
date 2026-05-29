"""Brain-first voice routing for FRIDAY.

When ``JARVIS_BRAIN_FIRST=1`` (default), open-ended utterances go to the tool
agent before the legacy regex ladder in ``main.process_command``.

Fast paths (exit, help, volume) stay instant — no LLM round-trip.
"""

from __future__ import annotations

import os
import traceback
from typing import Callable, Optional

from jarvis_exceptions import JarvisExitRequest

SpeakFn = Callable[[str], None]

_STOPWORDS = {"the", "a", "an"}


def normalize_voice_query(q: str) -> str:
    """Strip wake words and filler from a voice transcript."""
    if not q or q.strip().lower() == "none":
        return "none"
    q = q.lower().strip()
    for noise in (
        "hey friday",
        "hey jarvis",
        "hey",
        "jarvis",
        "friday",
        "please",
        "can you",
        "okay",
        "ok",
    ):
        q = q.replace(noise, " ")
    parts = [p for p in q.split() if p not in _STOPWORDS]
    cleaned = " ".join(parts).strip(" ,.;:!?-")
    return cleaned or "none"


def brain_first_enabled() -> bool:
    return os.environ.get("JARVIS_BRAIN_FIRST", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _norm(query: str) -> str:
    return (query or "").strip().lower().rstrip(" .!?")


def is_fast_path(query: str) -> bool:
    q = _norm(query)
    if not q:
        return False
    if q in ("quit", "goodbye", "bye", "shutdown", "stop") or "exit" in q:
        return True
    if q == "help" or "what can you do" in q:
        return True
    if q in ("volume up", "volume down", "volume mute", "mute"):
        return True
    if "who made you" in q or "who created you" in q:
        return True
    return False


def help_text() -> str:
    return (
        "I can open apps, play music, control Spotify and HomeKit, search the web, "
        "tell time and weather, manage reminders and calendar, run routines, and answer from your documents. "
        "Try: daily briefing, morning reflection, what is on my screen, remind me in 10 minutes, "
        "calendar today, prep me for my next meeting, list routines, every weekday at 8 am daily briefing, "
        "search the web for ..., ask my documents about ..., learn that ..., sync now, private mode on, "
        "forget the last 5 minutes, list open loops, weekly digest, snooze for 30 minutes, "
        "undo, switch user to ..., or just ask naturally and I will figure out the tools. "
        "In passive mode say Hey Friday first, or disable JARVIS_PASSIVE_MODE for always listening."
    )


def try_fast_path(
    query: str,
    *,
    speak: SpeakFn,
    speak_reply: Optional[SpeakFn] = None,
) -> bool:
    """Handle instant local commands. Returns True when handled."""
    q = _norm(query)
    if not q:
        return False

    if q in ("quit", "goodbye", "bye", "shutdown", "stop") or "exit" in q:
        speak("Thanks for giving me your precious time Sir")
        raise JarvisExitRequest

    if q == "help" or "what can you do" in q:
        speak(help_text())
        return True

    if q in ("volume up", "volume down", "volume mute", "mute"):
        import pyautogui

        if q == "volume up":
            pyautogui.press("volumeup")
        elif q == "volume down":
            pyautogui.press("volumedown")
        else:
            pyautogui.press("volumemute")
        return True

    if "who made you" in q or "who created you" in q:
        speak("I have been created by Bhagya Rana.")
        return True

    return False


def invoke_agent_brain(
    query: str,
    voice_raw: Optional[str],
    *,
    speak: SpeakFn,
    speak_reply: SpeakFn,
    speak_filler: Callable[[], None],
) -> None:
    """Run the tool-using agent brain; speaks errors on failure."""
    import jarvis_brain as jb

    if not jb.is_brain_enabled():
        speak(
            "Sir, no reasoning engine is available. "
            "Set OPENAI_API_KEY or start Ollama with JARVIS_LOCAL_LLM=prefer."
        )
        return

    from dialogue_state import describe_state_for_prompt, remember_last_topic
    from memory.episodic_memory import (
        memory_auto_capture_user_profile,
        memory_build_context_for_prompt,
    )
    from sentiment import persona_mood_overlay, recent_mood_label

    utterance = (voice_raw or query or "").strip()
    try:
        memory_auto_capture_user_profile(utterance)
        episodic_prefill = memory_build_context_for_prompt(query=utterance)
        ds = describe_state_for_prompt()
        if ds:
            episodic_prefill = f"Dialogue state:\n{ds}\n\n{episodic_prefill}"
        mood_overlay = persona_mood_overlay(recent_mood_label())
        if mood_overlay:
            episodic_prefill = mood_overlay.strip() + "\n\n" + episodic_prefill
        speak_filler()
        reply = jb.run_agent_brain(
            user_utterance=utterance,
            episodic_prefill=episodic_prefill,
        )
        if reply:
            speak_reply(reply)
            remember_last_topic(utterance[:80])
    except JarvisExitRequest:
        speak("Thanks for giving me your precious time Sir")
        raise
    except Exception as exc:
        traceback.print_exc()
        low = str(exc).lower()
        if any(t in low for t in ("429", "quota", "insufficient_quota", "billing", "402")):
            speak(
                "Sir, the cloud brain is out of quota. "
                "Start Ollama and keep JARVIS_LOCAL_LLM=prefer for local fallback."
            )
        elif "ollama" in low or "no brain available" in low:
            speak(
                "Sir, no reasoning engine is available. "
                "Set OPENAI_API_KEY or start Ollama with JARVIS_LOCAL_LLM=prefer."
            )
        else:
            speak("Sir, the reasoning engine hit an error trying that phrase.")


__all__ = [
    "brain_first_enabled",
    "help_text",
    "invoke_agent_brain",
    "is_fast_path",
    "normalize_voice_query",
    "try_fast_path",
]
