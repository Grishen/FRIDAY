"""Reminders / scheduled alerts for the assistant.

Storage: SQLite (``data/jarvis_reminders.sqlite``) so reminders survive restarts.

Time parsing is intentionally dependency-free and supports common voice phrasings:

- "remind me to X in 5 minutes"
- "remind me to X in 2 hours"
- "remind me to X at 7am"
- "remind me to X at 7:30 pm"
- "remind me to X tomorrow at 9"
- "remind me to X at 9 tomorrow"

A background daemon thread polls for due reminders and fires them via
``platform_services.show_desktop_notification`` and (optionally) a callback
that can speak the message aloud.
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
_DATA = ROOT / "data"
_DB_PATH = _DATA / "jarvis_reminders.sqlite"
_DB_LOCK = threading.Lock()


# ---------- storage ----------

def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            due_at REAL NOT NULL,
            created_at REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            recurrence TEXT NOT NULL DEFAULT ''
        )
        """
    )
    # Backfill column for existing installs.
    try:
        cur = conn.execute("PRAGMA table_info(reminders)")
        cols = {row[1] for row in cur.fetchall()}
        if "recurrence" not in cols:
            conn.execute("ALTER TABLE reminders ADD COLUMN recurrence TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS reminders_due_idx ON reminders (status, due_at)"
    )


def _connect() -> sqlite3.Connection:
    _DATA.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB_PATH)


def add_reminder(message: str, due_at_epoch: float, *, recurrence: str = "") -> int:
    msg = (message or "").strip()
    if not msg:
        raise ValueError("Reminder message cannot be empty.")
    with _DB_LOCK:
        conn = _connect()
        try:
            _ensure(conn)
            cur = conn.execute(
                """
                INSERT INTO reminders (message, due_at, created_at, status, recurrence)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (msg, float(due_at_epoch), time.time(), (recurrence or "").strip().lower()),
            )
            conn.commit()
            rid = int(cur.lastrowid or 0)
        finally:
            conn.close()

    try:
        from action_history import record_action

        record_action(
            kind="reminder",
            payload={
                "summary": msg,
                "due_at": float(due_at_epoch),
                "recurrence": (recurrence or "").strip().lower(),
            },
            undo_data={"reminder_id": rid},
        )
    except Exception:
        pass
    return rid


def list_pending_reminders(*, limit: int = 20) -> list[tuple[int, str, float, str]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            _ensure(conn)
            cur = conn.execute(
                """
                SELECT id, message, due_at, COALESCE(recurrence, '') FROM reminders
                WHERE status = 'pending'
                ORDER BY due_at ASC
                LIMIT ?
                """,
                (max(1, limit),),
            )
            return [
                (int(r[0]), str(r[1]), float(r[2]), str(r[3]))
                for r in cur.fetchall()
            ]
        finally:
            conn.close()


def cancel_reminder(reminder_id: int) -> bool:
    with _DB_LOCK:
        conn = _connect()
        try:
            _ensure(conn)
            cur = conn.execute(
                "UPDATE reminders SET status='cancelled' WHERE id=? AND status='pending'",
                (int(reminder_id),),
            )
            conn.commit()
            return (cur.rowcount or 0) > 0
        finally:
            conn.close()


def _claim_due_reminders(now_epoch: float) -> list[tuple[int, str, float]]:
    """Atomically deliver due reminders. One-shot rows are marked fired; recurring rows have their due_at advanced."""
    with _DB_LOCK:
        conn = _connect()
        try:
            _ensure(conn)
            cur = conn.execute(
                """
                SELECT id, message, due_at, COALESCE(recurrence, '') FROM reminders
                WHERE status = 'pending' AND due_at <= ?
                ORDER BY due_at ASC
                """,
                (float(now_epoch),),
            )
            rows = cur.fetchall()
            fired_for_caller: list[tuple[int, str, float]] = []
            for rid, msg, due_at, recurrence in rows:
                rid_i = int(rid)
                due_f = float(due_at)
                rec = (recurrence or "").strip().lower()
                fired_for_caller.append((rid_i, str(msg), due_f))
                if rec:
                    next_due = _advance_recurrence(due_f, rec, after_epoch=float(now_epoch))
                    if next_due is None:
                        conn.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid_i,))
                    else:
                        conn.execute(
                            "UPDATE reminders SET due_at=? WHERE id=?",
                            (next_due, rid_i),
                        )
                else:
                    conn.execute("UPDATE reminders SET status='fired' WHERE id=?", (rid_i,))
            if rows:
                conn.commit()
            return fired_for_caller
        finally:
            conn.close()


_WEEKDAY_NAMES = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}
_WEEKDAYS_SET = {0, 1, 2, 3, 4}


def _advance_recurrence(prev_due: float, rec: str, *, after_epoch: float) -> Optional[float]:
    """Compute the next due epoch after a recurring reminder fires."""
    rec = (rec or "").strip().lower()
    if not rec:
        return None
    base = _dt.datetime.fromtimestamp(prev_due)

    if rec in ("daily", "every day", "everyday"):
        candidate = base + _dt.timedelta(days=1)
        while candidate.timestamp() <= after_epoch:
            candidate += _dt.timedelta(days=1)
        return candidate.timestamp()

    if rec in ("weekly", "every week"):
        candidate = base + _dt.timedelta(days=7)
        while candidate.timestamp() <= after_epoch:
            candidate += _dt.timedelta(days=7)
        return candidate.timestamp()

    if rec in ("hourly", "every hour"):
        candidate = base + _dt.timedelta(hours=1)
        while candidate.timestamp() <= after_epoch:
            candidate += _dt.timedelta(hours=1)
        return candidate.timestamp()

    if rec in ("weekdays", "every weekday"):
        days = _WEEKDAYS_SET
    elif rec.startswith("weekly:"):
        names = [s.strip() for s in rec.split(":", 1)[1].split(",") if s.strip()]
        days = {_WEEKDAY_NAMES[n] for n in names if n in _WEEKDAY_NAMES}
        if not days:
            return None
    else:
        return None

    candidate = base + _dt.timedelta(days=1)
    for _ in range(14):
        if candidate.weekday() in days and candidate.timestamp() > after_epoch:
            return candidate.timestamp()
        candidate += _dt.timedelta(days=1)
    return None


# ---------- natural time parsing ----------

_REMIND_PREFIXES = (
    "remind me to ",
    "remind me that ",
    "remind me ",
    "set a reminder to ",
    "set reminder to ",
    "set a reminder ",
)

_TIME_PATTERNS = [
    # in N minutes / hours / seconds / days
    re.compile(r"\bin\s+(\d{1,3})\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\b", re.I),
    # at H[:MM][ ]am/pm
    re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I),
    # at H:MM (24h)
    re.compile(r"\bat\s+(\d{1,2}):(\d{2})\b"),
    # H[:MM] am/pm (no 'at')
    re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I),
]


def _strip_prefix(text: str) -> str:
    low = text.lower()
    for p in _REMIND_PREFIXES:
        if low.startswith(p):
            return text[len(p) :]
    return text


def _now() -> _dt.datetime:
    return _dt.datetime.now()


_RECURRENCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bevery\s+day\b|\bdaily\b|\beveryday\b", re.I), "daily"),
    (re.compile(r"\bevery\s+weekday\b|\bweekdays\b|\bevery\s+work(?:ing)?\s+day\b", re.I), "weekdays"),
    (re.compile(r"\bevery\s+hour\b|\bhourly\b", re.I), "hourly"),
    (re.compile(r"\bevery\s+week\b|\bweekly\b", re.I), "weekly"),
]
_WEEKDAY_RECURRENCE_RE = re.compile(
    r"\bevery\s+("
    r"mon|monday|tue|tues|tuesday|wed|weds|wednesday|thu|thur|thurs|thursday|"
    r"fri|friday|sat|saturday|sun|sunday"
    r")(?:s)?\b",
    re.I,
)


def _detect_recurrence(text: str) -> tuple[str, str]:
    """Return (recurrence_spec, cleaned_text_with_phrase_stripped)."""
    cleaned = text
    rec = ""
    m = _WEEKDAY_RECURRENCE_RE.search(cleaned)
    if m:
        day = m.group(1).lower()
        idx = _WEEKDAY_NAMES.get(day)
        if idx is not None:
            inv = {v: k for k, v in _WEEKDAY_NAMES.items() if len(k) <= 3}
            short = inv.get(idx, day[:3])
            rec = f"weekly:{short}"
            cleaned = (cleaned[: m.start()] + cleaned[m.end() :]).strip()
            return rec, cleaned

    for pat, label in _RECURRENCE_PATTERNS:
        mm = pat.search(cleaned)
        if mm:
            rec = label
            cleaned = (cleaned[: mm.start()] + cleaned[mm.end() :]).strip()
            return rec, cleaned
    return "", cleaned


def parse_reminder(text: str) -> tuple[str, Optional[_dt.datetime], str]:
    """
    Return ``(message, due_datetime, recurrence_spec)``.

    - ``due_datetime`` is ``None`` if no recognizable time phrase is found.
    - ``recurrence_spec`` is one of: ``''`` (one-shot), ``'daily'``, ``'weekdays'``,
      ``'weekly'``, ``'hourly'``, or ``'weekly:<mon|tue|wed|...>'``.
    """
    raw = (text or "").strip()
    if not raw:
        return "", None, ""

    body = _strip_prefix(raw).strip()
    recurrence, body = _detect_recurrence(body)
    want_tomorrow = False
    if re.search(r"\btomorrow\b", body, re.I):
        want_tomorrow = True
        body = re.sub(r"\btomorrow\b", "", body, flags=re.I).strip()

    due: Optional[_dt.datetime] = None
    cleaned = body

    # 1) relative offset
    m = _TIME_PATTERNS[0].search(body)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith(("sec",)):
            delta = _dt.timedelta(seconds=n)
        elif unit.startswith(("min",)):
            delta = _dt.timedelta(minutes=n)
        elif unit.startswith(("hour", "hr")):
            delta = _dt.timedelta(hours=n)
        else:
            delta = _dt.timedelta(days=n)
        due = _now() + delta
        cleaned = (body[: m.start()] + body[m.end() :]).strip(" ,.")
    else:
        # 2/3/4) absolute clock times
        for idx in (1, 2, 3):
            mm = _TIME_PATTERNS[idx].search(body)
            if not mm:
                continue
            hour = int(mm.group(1))
            minute = int(mm.group(2)) if mm.lastindex and mm.lastindex >= 2 and mm.group(2) else 0
            ampm = mm.group(3).lower() if (idx in (1, 3) and mm.lastindex and mm.lastindex >= 3) else None
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                continue
            base = _now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            if want_tomorrow:
                base = base + _dt.timedelta(days=1)
            elif base <= _now():
                # If clock time already passed today, push to tomorrow.
                base = base + _dt.timedelta(days=1)
            due = base
            cleaned = (body[: mm.start()] + body[mm.end() :]).strip(" ,.")
            break

    # Normalize message
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:!?-")
    cleaned = re.sub(r"^(to|that|about)\s+", "", cleaned, flags=re.I).strip()
    if not cleaned:
        cleaned = body.strip()

    # If a recurrence was detected but no explicit time, pick a sensible first occurrence.
    if recurrence and due is None:
        if recurrence == "hourly":
            due = _now() + _dt.timedelta(hours=1)
        elif recurrence == "daily":
            due = _now() + _dt.timedelta(days=1)
        elif recurrence == "weekly":
            due = _now() + _dt.timedelta(weeks=1)
        elif recurrence == "weekdays":
            cand = _now() + _dt.timedelta(days=1)
            while cand.weekday() not in _WEEKDAYS_SET:
                cand += _dt.timedelta(days=1)
            due = cand
        elif recurrence.startswith("weekly:"):
            day_token = recurrence.split(":", 1)[1].strip()
            target = _WEEKDAY_NAMES.get(day_token)
            if target is not None:
                offset = (target - _now().weekday()) % 7
                if offset == 0:
                    offset = 7
                due = _now() + _dt.timedelta(days=offset)
    return cleaned, due, recurrence


def looks_like_reminder(text: str) -> bool:
    low = (text or "").lower().strip()
    return any(low.startswith(p) for p in _REMIND_PREFIXES)


def describe_reminder_due(due: _dt.datetime) -> str:
    return due.strftime("%a %b %d at %I:%M %p").replace(" 0", " ")


# ---------- background scheduler ----------

_scheduler_started = threading.Event()
_scheduler_stop = threading.Event()


def start_reminder_scheduler(
    *,
    on_fire: Optional[Callable[[str], None]] = None,
    poll_seconds: float = 15.0,
) -> None:
    """Start (idempotently) a daemon thread that polls for due reminders."""
    if _scheduler_started.is_set():
        return
    _scheduler_started.set()
    _scheduler_stop.clear()

    def _loop() -> None:
        try:
            from platform_services import show_desktop_notification
        except Exception:
            show_desktop_notification = None  # type: ignore[assignment]

        while not _scheduler_stop.is_set():
            try:
                due_now = _claim_due_reminders(time.time())
                for _rid, msg, _due in due_now:
                    try:
                        if show_desktop_notification is not None:
                            show_desktop_notification("Reminder", msg)
                    except Exception:
                        pass
                    if on_fire is not None:
                        try:
                            on_fire(msg)
                        except Exception:
                            pass
            except Exception:
                pass
            _scheduler_stop.wait(max(2.0, float(poll_seconds)))

    t = threading.Thread(target=_loop, name="jarvis-reminders", daemon=True)
    t.start()


def stop_reminder_scheduler() -> None:
    _scheduler_stop.set()
    _scheduler_started.clear()


__all__ = [
    "add_reminder",
    "cancel_reminder",
    "describe_reminder_due",
    "list_pending_reminders",
    "looks_like_reminder",
    "parse_reminder",
    "start_reminder_scheduler",
    "stop_reminder_scheduler",
]
