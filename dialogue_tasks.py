"""Multi-step slot-filling for incomplete voice commands.

When a user starts a reminder, email, or calendar request but omits a required
field, we open a ``pending_task`` in :mod:`dialogue_state` and collect the
missing pieces across turns instead of failing or blocking on ``take_command()``.

Supported tasks:
    - ``reminder``  — needs ``message`` and ``when``
    - ``email``     — needs ``body`` (optional ``subject``)
    - ``calendar``  — needs ``title`` and ``start`` (optional ``duration``)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from dialogue_state import close_task, get_pending_task, open_task, update_task_slot


def _addr() -> str:
    try:
        from personas import get_address

        a = get_address()
        return f", {a}" if a else ""
    except Exception:
        return ", Sir"


# --------------------------------------------------------------------------- #
# Open incomplete commands
# --------------------------------------------------------------------------- #


def maybe_open_incomplete_command(query: str, voice_raw: str) -> bool:
    """
    If ``query`` looks like an incomplete multi-step command, open a pending
    task and return True (caller should not re-process the same command).
    """
    if get_pending_task():
        return False

    raw = (voice_raw or query or "").strip()
    low = (query or "").lower()
    low_stripped = low.strip()

    if low_stripped.startswith(("remind me", "set a reminder", "set reminder")):
        from reminders import parse_reminder

        msg, due, recurrence = parse_reminder(raw)
        slots: dict = {"recurrence": recurrence or ""}
        if msg:
            slots["message"] = msg
        if due is not None:
            slots["when"] = due.isoformat()
        missing = _missing_reminder_slots(slots)
        if missing:
            open_task("reminder", slots=slots, prompt=_prompt_for("reminder", missing[0]))
            return True
        return False

    if any(
        low_stripped == p or low_stripped.startswith(p + " ")
        for p in ("email myself", "email me", "send myself")
    ):
        body = ""
        for p in ("email myself", "email me", "send myself"):
            if low_stripped == p:
                body = ""
                break
            if low_stripped.startswith(p + " "):
                body = low_stripped[len(p) + 1 :].strip()
                break
        if not body:
            open_task("email", slots={}, prompt="What should I email you?")
            return True
        return False

    if any(
        low_stripped.startswith(p)
        for p in (
            "schedule ",
            "add to calendar ",
            "add calendar event ",
            "create calendar event ",
            "put on my calendar ",
        )
    ):
        from calendar_service import parse_calendar_phrase

        phrase = _calendar_phrase(raw)
        title, start_dt, duration = parse_calendar_phrase(phrase)
        slots: dict = {}
        if title:
            slots["title"] = title
        if start_dt is not None:
            slots["start"] = start_dt.isoformat()
        if duration:
            slots["duration"] = int(duration)
        missing = _missing_calendar_slots(slots)
        if missing:
            open_task("calendar", slots=slots, prompt=_prompt_for("calendar", missing[0]))
            return True
        return False

    return False


def _extract_after_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    low = text.lower()
    for p in prefixes:
        if low.startswith(p):
            return text[len(p) :].strip()
    return text.strip()


def _calendar_phrase(raw: str) -> str:
    low = raw.lower()
    for p in (
        "put on my calendar ",
        "add to calendar ",
        "add calendar event ",
        "create calendar event ",
        "schedule ",
    ):
        if low.startswith(p):
            return raw[len(p) :].strip()
    return raw.strip()


def _missing_reminder_slots(slots: dict) -> list[str]:
    missing: list[str] = []
    if not (slots.get("message") or "").strip():
        missing.append("message")
    if not slots.get("when"):
        missing.append("when")
    return missing


def _missing_calendar_slots(slots: dict) -> list[str]:
    missing: list[str] = []
    if not (slots.get("title") or "").strip():
        missing.append("title")
    if not slots.get("start"):
        missing.append("start")
    return missing


def _prompt_for(task: str, slot: str) -> str:
    prompts = {
        ("reminder", "message"): "What should I remind you about?",
        ("reminder", "when"): "When should I remind you?",
        ("email", "body"): "What should I email you?",
        ("calendar", "title"): "What should I call this event?",
        ("calendar", "start"): "When should I schedule it?",
    }
    return prompts.get((task, slot), "Could you give me a bit more detail?")


# --------------------------------------------------------------------------- #
# Handle pending task turns
# --------------------------------------------------------------------------- #


_CANCEL_RE = re.compile(
    r"\b(cancel|never mind|nevermind|forget it|stop|abort|skip)\b",
    re.I,
)


def handle_pending_task(query: str, voice_raw: str) -> Optional[str]:
    """
    If a pending task is open, consume this turn to fill a slot or finish.

    Returns speakable text if handled, else ``None`` (caller runs normal routing).
    """
    task = get_pending_task()
    if not task:
        return None

    raw = (voice_raw or query or "").strip()
    low = (query or "").lower().strip()
    if _CANCEL_RE.search(low):
        close_task()
        return f"Cancelled{_addr()}."

    name = (task.get("name") or "").strip()
    slots = dict(task.get("slots") or {})

    if name == "reminder":
        return _handle_reminder_task(slots, raw, low)
    if name == "email":
        return _handle_email_task(slots, raw)
    if name == "calendar":
        return _handle_calendar_task(slots, raw)

    close_task()
    return None


def _handle_reminder_task(slots: dict, raw: str, low: str) -> Optional[str]:
    from reminders import add_reminder, describe_reminder_due, parse_reminder

    missing = _missing_reminder_slots(slots)
    if not missing:
        return _finish_reminder(slots)

    slot = missing[0]
    if slot == "message":
        if low.startswith(("remind me", "set reminder")):
            msg, due, recurrence = parse_reminder(raw)
            if msg:
                update_task_slot("message", msg)
                slots["message"] = msg
            if due is not None:
                update_task_slot("when", due.isoformat())
                slots["when"] = due.isoformat()
            if recurrence:
                update_task_slot("recurrence", recurrence)
                slots["recurrence"] = recurrence
        else:
            update_task_slot("message", raw)
            slots["message"] = raw
    elif slot == "when":
        wrapped = f"remind me {raw}"
        _msg, due, recurrence = parse_reminder(wrapped)
        if due is None:
            _msg2, due2, rec2 = parse_reminder(f"remind me to check in {raw}")
            due, recurrence = due2, rec2
        if due is None:
            return f"I still need a time — try 'in 10 minutes' or 'at 3pm'{_addr()}."
        update_task_slot("when", due.isoformat())
        slots["when"] = due.isoformat()
        if recurrence and not slots.get("recurrence"):
            update_task_slot("recurrence", recurrence)
            slots["recurrence"] = recurrence

    missing = _missing_reminder_slots(slots)
    if missing:
        return _prompt_for("reminder", missing[0])
    return _finish_reminder(slots)


def _finish_reminder(slots: dict) -> str:
    from reminders import add_reminder, describe_reminder_due

    close_task()
    msg = (slots.get("message") or "").strip()
    when_raw = slots.get("when")
    try:
        due = datetime.fromisoformat(when_raw) if when_raw else None
    except (TypeError, ValueError):
        due = None
    if not msg or due is None:
        return f"I couldn't finish that reminder{_addr()}."
    recurrence = (slots.get("recurrence") or "").strip()
    rid = add_reminder(msg, due.timestamp(), recurrence=recurrence or None)
    recur_phrase = f" (recurring {recurrence})" if recurrence else ""
    return f"Reminder {rid} set for {describe_reminder_due(due)}{recur_phrase}: {msg}."


def _handle_email_task(slots: dict, raw: str) -> Optional[str]:
    from outgoing import email_myself

    if not raw.strip():
        return "What should I email you?"
    update_task_slot("body", raw.strip())
    close_task()
    subject = (slots.get("subject") or "Note from Jarvis").strip()
    return email_myself(raw.strip(), subject=subject)


def _handle_calendar_task(slots: dict, raw: str) -> Optional[str]:
    from calendar_service import calendar_available, calendar_create_event, calendar_unavailable_message, parse_calendar_phrase

    if not calendar_available():
        close_task()
        return f"{calendar_unavailable_message()}{_addr()}."

    missing = _missing_calendar_slots(slots)
    if not missing:
        return _finish_calendar(slots)

    slot = missing[0]
    if slot == "title":
        update_task_slot("title", raw.strip())
        slots["title"] = raw.strip()
    elif slot == "start":
        title = (slots.get("title") or "Event").strip()
        _t, start_dt, duration = parse_calendar_phrase(f"{title} {raw}")
        if start_dt is None:
            return f"When should I schedule it? Try 'tomorrow at 3pm'{_addr()}."
        update_task_slot("start", start_dt.isoformat())
        slots["start"] = start_dt.isoformat()
        if duration and not slots.get("duration"):
            update_task_slot("duration", int(duration))
            slots["duration"] = int(duration)

    missing = _missing_calendar_slots(slots)
    if missing:
        return _prompt_for("calendar", missing[0])
    return _finish_calendar(slots)


def _finish_calendar(slots: dict) -> str:
    from calendar_service import calendar_create_event

    close_task()
    title = (slots.get("title") or "Event").strip()
    try:
        start_dt = datetime.fromisoformat(slots["start"])
    except (TypeError, ValueError, KeyError):
        return f"I couldn't parse the event time{_addr()}."
    duration = int(slots.get("duration") or 30)
    result = calendar_create_event(title=title, start=start_dt, duration_minutes=duration)
    return result or f"Scheduled {title}{_addr()}."


def try_finish_reminder(voice_raw: str) -> Optional[str]:
    """If ``voice_raw`` is a complete reminder phrase, execute and return confirmation."""
    from reminders import parse_reminder

    msg, due, recurrence = parse_reminder(voice_raw)
    if not msg or due is None:
        return None
    return _finish_reminder(
        {"message": msg, "when": due.isoformat(), "recurrence": recurrence or ""}
    )


def try_finish_calendar(voice_raw: str) -> Optional[str]:
    from calendar_service import calendar_available, parse_calendar_phrase

    if not calendar_available():
        return None
    phrase = _calendar_phrase(voice_raw)
    title, start_dt, duration = parse_calendar_phrase(phrase)
    if not title or start_dt is None:
        return None
    return _finish_calendar(
        {"title": title, "start": start_dt.isoformat(), "duration": int(duration or 30)}
    )


__all__ = [
    "handle_pending_task",
    "maybe_open_incomplete_command",
    "try_finish_calendar",
    "try_finish_reminder",
]
