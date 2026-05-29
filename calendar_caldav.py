"""CalDAV calendar backend (Google Calendar, iCloud, Fastmail, etc.).

Env:
    JARVIS_CALDAV_URL       — CalDAV collection URL
    JARVIS_CALDAV_USERNAME  — account email / username
    JARVIS_CALDAV_PASSWORD  — app password or account password
    JARVIS_CALDAV_CALENDAR  — optional calendar name (default: first writable)

Google Calendar setup:
    1. Enable 2FA on Google account.
    2. Create an App Password: https://myaccount.google.com/apppasswords
    3. Set:
         JARVIS_CALDAV_URL=https://apidata.googleusercontent.com/caldav/v2/YOUR_EMAIL/events
         JARVIS_CALDAV_USERNAME=YOUR_EMAIL
         JARVIS_CALDAV_PASSWORD=your-16-char-app-password
         JARVIS_CALENDAR_BACKEND=caldav
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
from typing import Any, Optional

_CLIENT_LOCK = threading.Lock()
_CLIENT: Any = None
_CALENDAR: Any = None


def caldav_configured() -> bool:
    url = os.environ.get("JARVIS_CALDAV_URL", "").strip()
    user = os.environ.get("JARVIS_CALDAV_USERNAME", "").strip()
    password = os.environ.get("JARVIS_CALDAV_PASSWORD", "").strip()
    return bool(url and user and password)


def _import_caldav():
    try:
        import caldav
    except ImportError as exc:
        raise RuntimeError(
            "CalDAV backend requires: pip install -r requirements-calendar.txt"
        ) from exc
    return caldav


def _get_calendar():
    global _CLIENT, _CALENDAR
    with _CLIENT_LOCK:
        if _CALENDAR is not None:
            return _CALENDAR
        caldav = _import_caldav()
        url = os.environ.get("JARVIS_CALDAV_URL", "").strip()
        user = os.environ.get("JARVIS_CALDAV_USERNAME", "").strip()
        password = os.environ.get("JARVIS_CALDAV_PASSWORD", "").strip()
        if not (url and user and password):
            raise RuntimeError("CalDAV is not configured (URL, username, password).")

        _CLIENT = caldav.DAVClient(url=url, username=user, password=password)
        principal = _CLIENT.principal()
        calendars = principal.calendars()
        if not calendars:
            raise RuntimeError("No CalDAV calendars found for this account.")

        preferred = os.environ.get("JARVIS_CALDAV_CALENDAR", "").strip()
        if not preferred:
            preferred = os.environ.get("JARVIS_CALENDAR_NAME", "").strip()

        if preferred:
            low = preferred.lower()
            for cal in calendars:
                name = str(getattr(cal, "name", "") or "")
                if name.lower() == low or low in name.lower():
                    _CALENDAR = cal
                    return _CALENDAR

        _CALENDAR = calendars[0]
        return _CALENDAR


def caldav_available() -> bool:
    if not caldav_configured():
        return False
    try:
        _get_calendar()
        return True
    except Exception:
        return False


def _event_row(event: Any) -> Optional[dict[str, str]]:
    try:
        vevent = event.vobject_instance.vevent
        summary = str(getattr(vevent, "summary", None).value if getattr(vevent, "summary", None) else "Untitled")
        start = vevent.dtstart.value
        end = getattr(vevent, "dtend", None)
        end_val = end.value if end is not None else start

        if isinstance(start, _dt.date) and not isinstance(start, _dt.datetime):
            start = _dt.datetime.combine(start, _dt.time.min)
        if isinstance(end_val, _dt.date) and not isinstance(end_val, _dt.datetime):
            end_val = _dt.datetime.combine(end_val, _dt.time.min)

        if start.tzinfo is None:
            start = start.replace(tzinfo=_dt.timezone.utc).astimezone()
        else:
            start = start.astimezone()
        if end_val.tzinfo is None:
            end_val = end_val.replace(tzinfo=_dt.timezone.utc).astimezone()
        else:
            end_val = end_val.astimezone()

        cal_name = str(getattr(event, "parent", None).name if getattr(event, "parent", None) else "CalDAV")
        return {
            "title": summary.strip(),
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end_val.strftime("%Y-%m-%d %H:%M:%S"),
            "calendar": cal_name,
        }
    except Exception:
        return None


def _search_events(*, start: _dt.datetime, end: _dt.datetime, limit: int) -> list[dict[str, str]]:
    cal = _get_calendar()
    rows: list[dict[str, str]] = []
    events = cal.search(
        start=start,
        end=end,
        event=True,
        expand=True,
    )
    for event in events:
        row = _event_row(event)
        if row:
            rows.append(row)
        if len(rows) >= max(1, limit):
            break
    rows.sort(key=lambda r: r.get("start", ""))
    return rows[: max(1, limit)]


def caldav_today_events(*, limit: int = 8) -> list[dict[str, str]]:
    now = _dt.datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + _dt.timedelta(days=1)
    return _search_events(start=start, end=end, limit=limit)


def caldav_upcoming_events(*, hours: int = 24, limit: int = 8) -> list[dict[str, str]]:
    start = _dt.datetime.now().astimezone()
    end = start + _dt.timedelta(hours=max(1, min(72, hours)))
    return _search_events(start=start, end=end, limit=limit)


def caldav_recently_ended_events(
    *,
    within_minutes: int = 20,
    grace_minutes: int = 2,
    limit: int = 5,
) -> list[dict[str, str]]:
    now = _dt.datetime.now().astimezone()
    window_start = now - _dt.timedelta(minutes=max(1, within_minutes))
    grace_end = now - _dt.timedelta(minutes=max(0, grace_minutes))
    cal = _get_calendar()
    rows: list[dict[str, str]] = []
    events = cal.search(start=window_start, end=now, event=True, expand=True)
    for event in events:
        row = _event_row(event)
        if not row:
            continue
        try:
            end_dt = _dt.datetime.strptime(row["end"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
        if window_start <= end_dt <= grace_end:
            rows.append(row)
        if len(rows) >= max(1, limit):
            break
    rows.sort(key=lambda r: r.get("end", ""), reverse=True)
    return rows[: max(1, limit)]


def caldav_create_event(
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
    if start_dt.tzinfo is None:
        start_dt = start_dt.astimezone()
    end_dt = start_dt + _dt.timedelta(minutes=duration_minutes)

    cal = _get_calendar()
    cal.add_event(
        summary=title,
        dtstart=start_dt,
        dtend=end_dt,
        description=(notes or "").strip(),
    )
    cal_name = str(getattr(cal, "name", None) or "CalDAV")
    try:
        from action_history import record_action

        record_action(
            kind="calendar",
            payload={
                "title": title,
                "start": start_dt.isoformat(),
                "duration_minutes": duration_minutes,
                "calendar": cal_name,
                "backend": "caldav",
            },
            undo_data={
                "title": title,
                "start": start_dt.isoformat(),
                "calendar": cal_name,
                "backend": "caldav",
            },
        )
    except Exception:
        pass
    return (
        f"Event created in '{cal_name}' via CalDAV: '{title}' at "
        f"{start_dt.strftime('%a %b %d %I:%M %p')} for {duration_minutes} min."
    )


__all__ = [
    "caldav_available",
    "caldav_configured",
    "caldav_create_event",
    "caldav_recently_ended_events",
    "caldav_today_events",
    "caldav_upcoming_events",
]
