"""Meeting prep lines — combine calendar events with topic-thread context."""

from __future__ import annotations

import re
from typing import Optional


def _tokens_from_title(title: str) -> list[str]:
    stop = {"with", "the", "and", "for", "meeting", "call", "sync", "standup", "review"}
    return [t for t in re.findall(r"[A-Za-z']{3,}", title or "") if t.lower() not in stop]


def prep_line_for_event(title: str, *, minutes_until: int) -> Optional[str]:
    """
    Build a voice-friendly prep line for an upcoming calendar event.
    Pulls matching topic threads when the event title mentions a person/project.
    """
    title = (title or "").strip()
    if not title:
        return None

    thread_hint = ""
    try:
        from topic_threads import find_thread, list_threads

        for tok in _tokens_from_title(title):
            t = find_thread(tok)
            if t:
                notes = (t.notes or [])[-1:] if hasattr(t, "notes") else []
                note = notes[0][:80] if notes else ""
                thread_hint = f" Last time on {t.label}: {note}" if note else f" We have an open thread on {t.label}."
                break
        if not thread_hint:
            open_threads = list_threads(status="open", limit=20)
            for t in open_threads:
                if t.label.lower() in title.lower() or title.lower() in t.label.lower():
                    thread_hint = f" Related thread: {t.label}."
                    break
    except Exception:
        pass

    mins = max(1, int(minutes_until or 1))
    base = f"{title} in about {mins} minute{'s' if mins != 1 else ''}."
    if thread_hint:
        return f"Heads up — {base}{thread_hint} Want a quick prep summary?"
    return f"Want a quick prep before {title} in {mins} minutes?"


__all__ = ["prep_line_for_event"]
