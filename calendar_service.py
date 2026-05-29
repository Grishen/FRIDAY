"""Calendar read/write helpers.

Backends (``JARVIS_CALENDAR_BACKEND``):

- ``auto`` (default) — CalDAV when configured, else macOS Calendar.app on Darwin
- ``caldav`` — Google Calendar / iCloud / any CalDAV server (see ``calendar_caldav.py``)
- ``macos`` — native AppleScript against Calendar.app (Darwin only)

Env:

- ``JARVIS_CALENDAR_BACKEND`` — auto | caldav | macos
- ``JARVIS_CALENDAR_NAME`` — preferred calendar to write into (macOS / CalDAV name)
- ``JARVIS_CALDAV_URL`` / ``JARVIS_CALDAV_USERNAME`` / ``JARVIS_CALDAV_PASSWORD``
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
import sys
from typing import Optional


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _backend() -> str:
    mode = (os.environ.get("JARVIS_CALENDAR_BACKEND", "auto") or "auto").strip().lower()
    if mode == "caldav":
        try:
            from calendar_caldav import caldav_available

            return "caldav" if caldav_available() else ""
        except Exception:
            return ""
    if mode == "macos":
        return "macos" if _is_macos() and _macos_available() else ""
    # auto
    try:
        from calendar_caldav import caldav_configured, caldav_available

        if caldav_configured() and caldav_available():
            return "caldav"
    except Exception:
        pass
    if _is_macos() and _macos_available():
        return "macos"
    return ""


def calendar_backend_name() -> str:
    """Human-readable active backend (empty if none)."""
    b = _backend()
    if b == "caldav":
        return "CalDAV"
    if b == "macos":
        return "macOS Calendar"
    return ""


# ---------- macOS implementation ----------

def _osascript(script: str, *, timeout: float = 12.0) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        return False, err or out or f"osascript exit {result.returncode}"
    return True, out


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _preferred_calendar_name() -> str:
    return os.environ.get("JARVIS_CALENDAR_NAME", "").strip()


def _calendar_picker_clause() -> str:
    preferred = _preferred_calendar_name()
    if preferred:
        return f'set targetCal to first calendar whose name is "{_esc(preferred)}"\n'
    return (
        'set targetCal to missing value\n'
        'try\n'
        '    set targetCal to first calendar whose name is "Home"\n'
        'end try\n'
        'if targetCal is missing value then\n'
        '    set targetCal to first calendar of (calendars whose writable is true)\n'
        'end if\n'
    )


def _macos_available() -> bool:
    if not _is_macos():
        return False
    ok, _ = _osascript('tell application "Calendar" to count calendars')
    return ok


def _macos_today_events(*, limit: int = 8) -> list[dict[str, str]]:
    now = _dt.datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + _dt.timedelta(days=1)
    return _macos_events_between(start, end, limit=limit)


def _macos_upcoming_events(*, hours: int = 24, limit: int = 8) -> list[dict[str, str]]:
    start = _dt.datetime.now()
    end = start + _dt.timedelta(hours=max(1, min(72, hours)))
    return _macos_events_between(start, end, limit=limit)


def _macos_recently_ended_events(
    *,
    within_minutes: int = 20,
    grace_minutes: int = 2,
    limit: int = 5,
) -> list[dict[str, str]]:
    now = _dt.datetime.now()
    window_start = now - _dt.timedelta(minutes=max(1, within_minutes))
    grace_end = now - _dt.timedelta(minutes=max(0, grace_minutes))
    return _macos_events_ended_between(window_start, grace_end, now=now, limit=limit)


def _macos_events_between(
    start: _dt.datetime,
    end: _dt.datetime,
    *,
    limit: int,
) -> list[dict[str, str]]:
    sdate = start.strftime("%Y-%m-%d %H:%M:%S")
    edate = end.strftime("%Y-%m-%d %H:%M:%S")

    script = f'''
    set output to ""
    set theStart to date "{sdate}"
    set theEnd to date "{edate}"
    tell application "Calendar"
        repeat with c in calendars
            try
                set theEvents to (every event of c whose start date is greater than or equal to theStart and start date is less than theEnd)
                repeat with e in theEvents
                    set t to summary of e
                    set s to start date of e
                    set en to end date of e
                    set output to output & t & "|" & (s as string) & "|" & (en as string) & "|" & (name of c) & linefeed
                end repeat
            on error
            end try
        end repeat
    end tell
    return output
    '''
    ok, out = _osascript(script, timeout=20)
    if not ok or not out:
        return []
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        rows.append(
            {
                "title": parts[0].strip(),
                "start": parts[1].strip(),
                "end": parts[2].strip(),
                "calendar": parts[3].strip(),
            }
        )
        if len(rows) >= max(1, limit):
            break
    return rows


def _macos_events_ended_between(
    start: _dt.datetime,
    grace_end: _dt.datetime,
    *,
    now: _dt.datetime,
    limit: int,
) -> list[dict[str, str]]:
    sdate = start.strftime("%Y-%m-%d %H:%M:%S")
    edate = now.strftime("%Y-%m-%d %H:%M:%S")
    grace = grace_end.strftime("%Y-%m-%d %H:%M:%S")

    script = f'''
    set output to ""
    set theStart to date "{sdate}"
    set theEnd to date "{edate}"
    set theGrace to date "{grace}"
    tell application "Calendar"
        repeat with c in calendars
            try
                set theEvents to (every event of c whose end date is greater than or equal to theStart and end date is less than or equal to theEnd)
                repeat with e in theEvents
                    set en to end date of e
                    if en is less than or equal to theGrace then
                        set t to summary of e
                        set s to start date of e
                        set output to output & t & "|" & (s as string) & "|" & (en as string) & "|" & (name of c) & linefeed
                    end if
                end repeat
            on error
            end try
        end repeat
    end tell
    return output
    '''
    ok, out = _osascript(script, timeout=20)
    if not ok or not out:
        return []
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        rows.append(
            {
                "title": parts[0].strip(),
                "start": parts[1].strip(),
                "end": parts[2].strip(),
                "calendar": parts[3].strip(),
            }
        )
        if len(rows) >= max(1, limit):
            break
    return rows


def _macos_create_event(
    *,
    title: str,
    start: _dt.datetime,
    duration_minutes: int = 30,
    notes: str = "",
) -> str:
    title = (title or "").strip()
    if not title:
        return "Event title is required."

    duration_minutes = max(5, min(60 * 12, int(duration_minutes)))
    start_dt = start.replace(second=0, microsecond=0)
    end_dt = start_dt + _dt.timedelta(minutes=duration_minutes)

    sdate = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    edate = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    safe_title = _esc(title)
    safe_notes = _esc(notes or "")

    script = f'''
    set startDate to date "{sdate}"
    set endDate to date "{edate}"
    tell application "Calendar"
        {_calendar_picker_clause()}
        tell targetCal
            make new event with properties {{summary:"{safe_title}", start date:startDate, end date:endDate, description:"{safe_notes}"}}
        end tell
        set calName to name of targetCal
    end tell
    return calName
    '''
    ok, out = _osascript(script, timeout=15)
    if not ok:
        return f"Could not create event: {out[:200]}"
    cal_used = out or "Calendar"
    try:
        from action_history import record_action

        record_action(
            kind="calendar",
            payload={
                "title": title,
                "start": start_dt.isoformat(),
                "duration_minutes": duration_minutes,
                "calendar": cal_used,
                "backend": "macos",
            },
            undo_data={
                "title": title,
                "start": start_dt.isoformat(),
                "calendar": cal_used,
                "backend": "macos",
            },
        )
    except Exception:
        pass
    return (
        f"Event created in '{cal_used}': '{title}' at "
        f"{start_dt.strftime('%a %b %d %I:%M %p')} for {duration_minutes} min."
    )


# ---------- public API ----------

def calendar_available() -> bool:
    return bool(_backend())


def calendar_today_events(*, limit: int = 8) -> list[dict[str, str]]:
    backend = _backend()
    if backend == "caldav":
        from calendar_caldav import caldav_today_events

        return caldav_today_events(limit=limit)
    if backend == "macos":
        return _macos_today_events(limit=limit)
    return []


def calendar_upcoming_events(*, hours: int = 24, limit: int = 8) -> list[dict[str, str]]:
    backend = _backend()
    if backend == "caldav":
        from calendar_caldav import caldav_upcoming_events

        return caldav_upcoming_events(hours=hours, limit=limit)
    if backend == "macos":
        return _macos_upcoming_events(hours=hours, limit=limit)
    return []


def calendar_recently_ended_events(
    *,
    within_minutes: int = 20,
    grace_minutes: int = 2,
    limit: int = 5,
) -> list[dict[str, str]]:
    backend = _backend()
    if backend == "caldav":
        from calendar_caldav import caldav_recently_ended_events

        return caldav_recently_ended_events(
            within_minutes=within_minutes,
            grace_minutes=grace_minutes,
            limit=limit,
        )
    if backend == "macos":
        return _macos_recently_ended_events(
            within_minutes=within_minutes,
            grace_minutes=grace_minutes,
            limit=limit,
        )
    return []


def calendar_create_event(
    *,
    title: str,
    start: _dt.datetime,
    duration_minutes: int = 30,
    notes: str = "",
) -> str:
    backend = _backend()
    if backend == "caldav":
        from calendar_caldav import caldav_create_event

        return caldav_create_event(
            title=title,
            start=start,
            duration_minutes=duration_minutes,
            notes=notes,
        )
    if backend == "macos":
        return _macos_create_event(
            title=title,
            start=start,
            duration_minutes=duration_minutes,
            notes=notes,
        )
    return (
        "Calendar integration is not configured. On macOS use Calendar.app, or set "
        "JARVIS_CALDAV_URL + credentials for Google/iCloud CalDAV."
    )


# ---------- natural language helpers ----------

_DAY_OFFSETS = {
    "today": 0,
    "tomorrow": 1,
    "day after tomorrow": 2,
}


def parse_calendar_phrase(text: str) -> tuple[str, Optional[_dt.datetime], int]:
    """
    Parse loose phrases like:

      - "meeting with Alice tomorrow at 3pm for 1 hour"
      - "lunch at 12:30 today"
      - "doctor appointment on Friday at 9am for 45 minutes"

    Returns ``(title, start_datetime, duration_minutes)``. Falls back gracefully
    when parts are missing (start may be ``None``).
    """
    raw = (text or "").strip()
    if not raw:
        return "", None, 30

    body = raw
    body = re.sub(r"^(create|add|schedule|put)\s+(?:a\s+)?", "", body, flags=re.I)
    body = re.sub(r"^(event|calendar event|meeting|appointment)\s+", "", body, flags=re.I)

    now = _dt.datetime.now()
    base_date = now.replace(hour=0, minute=0, second=0, microsecond=0)

    day_match = re.search(r"\b(today|tomorrow|day after tomorrow)\b", body, re.I)
    if day_match:
        base_date += _dt.timedelta(days=_DAY_OFFSETS[day_match.group(1).lower()])
        body = (body[: day_match.start()] + body[day_match.end() :]).strip()
    else:
        weekday_match = re.search(
            r"\b(on\s+)?(mon|monday|tue|tues|tuesday|wed|weds|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)\b",
            body,
            re.I,
        )
        if weekday_match:
            from reminders import _WEEKDAY_NAMES  # type: ignore

            day_token = weekday_match.group(2).lower()
            target = _WEEKDAY_NAMES.get(day_token)
            if target is not None:
                offset = (target - now.weekday()) % 7
                if offset == 0:
                    offset = 7
                base_date += _dt.timedelta(days=offset)
                body = (body[: weekday_match.start()] + body[weekday_match.end() :]).strip()

    time_dt: Optional[_dt.datetime] = None
    time_match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", body, re.I)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        ampm = (time_match.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            time_dt = base_date.replace(hour=hour, minute=minute)
            if not ampm and time_dt <= now and base_date.date() == now.date():
                time_dt += _dt.timedelta(days=1)
        body = (body[: time_match.start()] + body[time_match.end() :]).strip()

    duration_minutes = 30
    dur_match = re.search(
        r"\bfor\s+(\d{1,3})\s*(minute|minutes|mins|min|hour|hours|hr|hrs)\b",
        body,
        re.I,
    )
    if dur_match:
        n = int(dur_match.group(1))
        unit = dur_match.group(2).lower()
        duration_minutes = n * 60 if unit.startswith("hour") or unit.startswith("hr") else n
        body = (body[: dur_match.start()] + body[dur_match.end() :]).strip()

    title = re.sub(r"\s+", " ", body).strip(" ,.;:!?-")
    title = re.sub(r"^(to|that|about|for|of)\s+", "", title, flags=re.I).strip()
    return title, time_dt, duration_minutes


def calendar_unavailable_message() -> str:
    return (
        "Calendar is not configured. On macOS, use Calendar.app (default), or set "
        "JARVIS_CALDAV_URL + credentials for Google/iCloud CalDAV "
        "(pip install -r requirements-calendar.txt)."
    )


__all__ = [
    "calendar_available",
    "calendar_backend_name",
    "calendar_create_event",
    "calendar_recently_ended_events",
    "calendar_today_events",
    "calendar_unavailable_message",
    "calendar_upcoming_events",
    "parse_calendar_phrase",
]
