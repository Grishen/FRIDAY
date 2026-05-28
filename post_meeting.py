"""Post-meeting capture — prompt after calendar events end, save notes to memory.

Flow:
1. Ambient daemon detects an event ended 2–20 minutes ago (configurable).
2. FRIDAY asks: "Your meeting X just ended — want to capture notes?"
3. User says yes → next utterance (or dedicated capture) is saved as meeting notes.
4. Notes go to episodic memory, topic threads, and optional open-loop extraction.

Storage: ``data/jarvis_post_meeting.sqlite``
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DB_LOCK = threading.Lock()
_PENDING: Optional[dict] = None
_PENDING_LOCK = threading.Lock()

_YES = re.compile(
    r"\b(yes|yeah|yep|sure|please|go ahead|capture|record|save notes|do it)\b",
    re.I,
)
_NO = re.compile(r"\b(no|nope|skip|not now|later|cancel|never mind)\b", re.I)


def _db_path() -> str:
    base = os.environ.get("JARVIS_DATA_DIR", "data")
    Path(base).mkdir(parents=True, exist_ok=True)
    return os.path.join(base, "jarvis_post_meeting.sqlite")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema() -> None:
    with _DB_LOCK, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS post_meeting_log (
                event_key   TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                ended_at    REAL NOT NULL,
                prompted_at REAL,
                captured_at REAL,
                notes       TEXT NOT NULL DEFAULT ''
            );
            """
        )


_ensure_schema()


def enabled() -> bool:
    return os.environ.get("JARVIS_POST_MEETING", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _grace_min() -> float:
    try:
        return max(1.0, float(os.environ.get("JARVIS_POST_MEETING_GRACE_MIN", "2")))
    except (TypeError, ValueError):
        return 2.0


def _window_min() -> float:
    try:
        return max(5.0, float(os.environ.get("JARVIS_POST_MEETING_WINDOW_MIN", "20")))
    except (TypeError, ValueError):
        return 20.0


def event_key(title: str, start: str) -> str:
    raw = f"{(title or '').strip()}|{(start or '').strip()}".lower()
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _was_prompted(key: str) -> bool:
    with _DB_LOCK, _conn() as c:
        row = c.execute(
            "SELECT prompted_at FROM post_meeting_log WHERE event_key=?",
            (key,),
        ).fetchone()
    return bool(row and row["prompted_at"])


def _mark_prompted(key: str, title: str, ended_at: float) -> None:
    now = time.time()
    with _DB_LOCK, _conn() as c:
        c.execute(
            """
            INSERT INTO post_meeting_log (event_key, title, ended_at, prompted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(event_key) DO UPDATE SET prompted_at=excluded.prompted_at
            """,
            (key, title, ended_at, now),
        )


def _save_notes(key: str, title: str, notes: str) -> None:
    now = time.time()
    with _DB_LOCK, _conn() as c:
        c.execute(
            """
            INSERT INTO post_meeting_log (event_key, title, ended_at, captured_at, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_key) DO UPDATE SET
                captured_at=excluded.captured_at,
                notes=excluded.notes
            """,
            (key, title, now, now, notes),
        )


def has_pending_capture() -> bool:
    with _PENDING_LOCK:
        if not _PENDING:
            return False
        if time.time() > float(_PENDING.get("expires_at") or 0):
            return False
        return True


def pending_title() -> str:
    with _PENDING_LOCK:
        return str((_PENDING or {}).get("title") or "")


def start_capture(title: str, *, event_key_val: str = "", minutes: float = 5.0) -> None:
    global _PENDING
    with _PENDING_LOCK:
        _PENDING = {
            "title": title,
            "event_key": event_key_val or event_key(title, str(time.time())),
            "expires_at": time.time() + max(60.0, minutes * 60),
        }


def clear_pending() -> None:
    global _PENDING
    with _PENDING_LOCK:
        _PENDING = None


def check_post_meeting_prompt() -> Optional[str]:
    """
    Return a speakable prompt if a calendar event recently ended and we haven't asked yet.
    """
    if not enabled() or has_pending_capture():
        return None
    try:
        from calendar_service import calendar_recently_ended_events
    except Exception:
        return None

    events = calendar_recently_ended_events(
        within_minutes=int(_window_min()),
        grace_minutes=int(_grace_min()),
        limit=3,
    )
    for ev in events:
        title = (ev.get("title") or "").strip()
        start = (ev.get("start") or "").strip()
        if not title:
            continue
        key = event_key(title, start)
        if _was_prompted(key):
            continue
        _mark_prompted(key, title, time.time())
        start_capture(title, event_key_val=key, minutes=8.0)
        short = title if len(title) <= 60 else title[:57] + "..."
        return f"Your meeting '{short}' just ended — want me to capture notes?"
    return None


def capture_meeting_notes(notes: str, *, title: str = "", event_key_val: str = "") -> str:
    """Persist meeting notes to memory + threads."""
    text = (notes or "").strip()
    if not text:
        return "I didn't catch any notes."

    with _PENDING_LOCK:
        pending = dict(_PENDING or {})
    title = (title or pending.get("title") or "Meeting").strip()
    key = event_key_val or pending.get("event_key") or event_key(title, str(time.time()))

    _save_notes(key, title, text)
    clear_pending()

    mem_line = f"meeting notes ({title}): {text[:500]}"
    try:
        from memory.episodic_memory import memory_append_turn

        memory_append_turn("note", mem_line)
    except Exception:
        pass

    try:
        from topic_threads import observe_utterance

        observe_utterance(f"meeting about {title}: {text}")
    except Exception:
        pass

    try:
        from open_loops import observe_utterance

        observe_utterance(text)
    except Exception:
        pass

    summary = text if len(text) <= 120 else text[:117] + "..."
    return f"Saved notes for {title}: {summary}"


def synthesize_meeting_summary(title: str, notes: str) -> str:
    """Optional LLM polish for stored notes."""
    notes = (notes or "").strip()
    if not notes:
        return ""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return notes
    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize meeting notes in 2-3 sentences for voice. "
                        "Include action items if any."
                    ),
                },
                {"role": "user", "content": f"Meeting: {title}\nNotes: {notes}"},
            ],
            temperature=0.3,
        )
        return (getattr(completion.choices[0].message, "content", None) or notes).strip()
    except Exception:
        return notes


def try_handle_post_meeting(query: str, *, voice_raw: str = "") -> Optional[str]:
    """
    Handle yes/no and in-progress note capture after a post-meeting prompt.
    """
    text = (voice_raw or query or "").strip()
    low = text.lower()

    if has_pending_capture():
        title = pending_title()
        if _NO.search(low) and len(low.split()) <= 8:
            clear_pending()
            return "Okay — skipped meeting notes."
        if len(text) >= 12 or not _YES.search(low):
            notes = text
            polished = synthesize_meeting_summary(title, notes)
            msg = capture_meeting_notes(polished or notes)
            return msg
        if _YES.search(low):
            return f"Go ahead — what should I remember from {title}?"

    if re.search(r"\bcapture (?:meeting )?notes\b", low):
        return "Tell me which meeting, or wait for me to prompt after your next call ends."

    if re.search(r"\b(meeting (?:just )?ended|post meeting|after (?:that|the) meeting)\b", low):
        start_capture("Recent meeting", minutes=8.0)
        return "What should I capture from that meeting?"

    return None


__all__ = [
    "capture_meeting_notes",
    "check_post_meeting_prompt",
    "clear_pending",
    "enabled",
    "has_pending_capture",
    "start_capture",
    "try_handle_post_meeting",
]
