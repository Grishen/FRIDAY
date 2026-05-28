"""Unified routines engine — scheduled and context-triggered automations.

Examples:
- Every weekday at 8:00 → daily briefing + open loops
- Every day at 22:30 → nightly reflection
- When Xcode is frontmost → enable glance mode

Storage: ``data/jarvis_routines.sqlite``

Voice:
- "list routines"
- "run routine morning"
- "every weekday at 8 am daily briefing and open loops"
- "when I'm in xcode enable glance mode"
- "delete routine 2"
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

_DB_LOCK = threading.Lock()
_STARTED = threading.Event()
_STOP = threading.Event()
_THREAD: Optional[threading.Thread] = None
_SPEAK_FN: Optional[Callable[[str], None]] = None

_WEEKDAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _db_path() -> str:
    base = os.environ.get("JARVIS_DATA_DIR", "data")
    Path(base).mkdir(parents=True, exist_ok=True)
    return os.path.join(base, "jarvis_routines.sqlite")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema() -> None:
    with _DB_LOCK, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS routines (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                trigger_kind  TEXT NOT NULL,
                trigger_json  TEXT NOT NULL,
                actions_json  TEXT NOT NULL,
                enabled       INTEGER NOT NULL DEFAULT 1,
                last_fired_at REAL NOT NULL DEFAULT 0,
                last_fire_key TEXT NOT NULL DEFAULT '',
                created_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_routines_enabled
                ON routines(enabled, trigger_kind);
            """
        )


_ensure_schema()


def enabled() -> bool:
    return os.environ.get("JARVIS_ROUTINES", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _tick_s() -> float:
    try:
        return max(15.0, float(os.environ.get("JARVIS_ROUTINES_TICK", "30")))
    except (TypeError, ValueError):
        return 30.0


@dataclass
class Routine:
    id: int
    name: str
    trigger_kind: str
    trigger: dict[str, Any]
    actions: list[dict[str, Any]]
    enabled: bool
    last_fired_at: float
    last_fire_key: str


def _row_to_routine(row: sqlite3.Row) -> Routine:
    return Routine(
        id=int(row["id"]),
        name=str(row["name"]),
        trigger_kind=str(row["trigger_kind"]),
        trigger=json.loads(row["trigger_json"] or "{}"),
        actions=json.loads(row["actions_json"] or "[]"),
        enabled=bool(row["enabled"]),
        last_fired_at=float(row["last_fired_at"] or 0),
        last_fire_key=str(row["last_fire_key"] or ""),
    )


def add_routine(
    name: str,
    *,
    trigger_kind: str,
    trigger: dict[str, Any],
    actions: list[dict[str, Any]],
) -> int:
    now = time.time()
    with _DB_LOCK, _conn() as c:
        cur = c.execute(
            "INSERT INTO routines (name, trigger_kind, trigger_json, actions_json, enabled, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (
                name.strip(),
                trigger_kind.strip(),
                json.dumps(trigger),
                json.dumps(actions),
                now,
            ),
        )
        return int(cur.lastrowid)


def list_routines(*, include_disabled: bool = True) -> list[Routine]:
    with _DB_LOCK, _conn() as c:
        if include_disabled:
            rows = c.execute("SELECT * FROM routines ORDER BY id").fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM routines WHERE enabled=1 ORDER BY id"
            ).fetchall()
    return [_row_to_routine(r) for r in rows]


def get_routine(routine_id: int) -> Optional[Routine]:
    with _DB_LOCK, _conn() as c:
        row = c.execute("SELECT * FROM routines WHERE id=?", (int(routine_id),)).fetchone()
    return _row_to_routine(row) if row else None


def find_routine_by_name(name: str) -> Optional[Routine]:
    needle = (name or "").strip().lower()
    for r in list_routines():
        if r.name.lower() == needle:
            return r
    return None


def set_routine_enabled(routine_id: int, enabled_flag: bool) -> bool:
    with _DB_LOCK, _conn() as c:
        cur = c.execute(
            "UPDATE routines SET enabled=? WHERE id=?",
            (1 if enabled_flag else 0, int(routine_id)),
        )
        return cur.rowcount > 0


def delete_routine(routine_id: int) -> bool:
    with _DB_LOCK, _conn() as c:
        cur = c.execute("DELETE FROM routines WHERE id=?", (int(routine_id),))
        return cur.rowcount > 0


def _mark_fired(routine_id: int, fire_key: str) -> None:
    now = time.time()
    with _DB_LOCK, _conn() as c:
        c.execute(
            "UPDATE routines SET last_fired_at=?, last_fire_key=? WHERE id=?",
            (now, fire_key, int(routine_id)),
        )


def _parse_time(text: str) -> tuple[int, int]:
    text = (text or "").lower().strip()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not m:
        return 8, 0
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return max(0, min(23, hour)), max(0, min(59, minute))


def _parse_weekdays(text: str) -> list[int]:
    low = (text or "").lower()
    if "weekday" in low or "weekdays" in low or "workday" in low:
        return [0, 1, 2, 3, 4]
    if "weekend" in low or "weekends" in low:
        return [5, 6]
    if "every day" in low or "daily" in low:
        return list(range(7))
    days: list[int] = []
    for token, idx in _WEEKDAY_NAMES.items():
        if re.search(rf"\b{token}\b", low):
            if idx not in days:
                days.append(idx)
    return sorted(days) if days else list(range(7))


def _parse_actions(text: str) -> list[dict[str, Any]]:
    low = (text or "").lower()
    actions: list[dict[str, Any]] = []
    if "briefing" in low or "morning briefing" in low:
        actions.append({"type": "briefing"})
    if "reflection" in low:
        actions.append({"type": "reflection"})
    if "open loop" in low or "open loops" in low:
        actions.append({"type": "open_loops"})
    if "weekly digest" in low or "week in review" in low:
        actions.append({"type": "weekly_digest"})
    if "calendar" in low:
        actions.append({"type": "calendar_today"})
    if "glance mode on" in low or "enable glance" in low:
        actions.append({"type": "glance_on"})
    if "glance mode off" in low or "disable glance" in low:
        actions.append({"type": "glance_off"})
    if "good night" in low or "goodnight" in low:
        actions.append({"type": "homekit_scene", "name": "good night"})
    m = re.search(r"\bsay\s+(.+)$", text, re.I)
    if m:
        actions.append({"type": "speak", "text": m.group(1).strip()})
    return actions


def parse_and_create_routine(text: str) -> str:
    """Parse a natural-language routine definition and persist it."""
    raw = (text or "").strip()
    if not raw:
        return "Tell me when and what to run — e.g. every weekday at 8 am daily briefing."

    low = raw.lower()

    m = re.search(
        r"(?:when i(?:'?m| am) in|when in|when using|while in)\s+(.+?)\s+(?:enable|start|turn on|run)\s+(.+)",
        low,
    )
    if m:
        app = m.group(1).strip()
        action_text = m.group(2).strip()
        actions = _parse_actions(action_text)
        if not actions:
            return "I need at least one action — briefing, reflection, glance mode, etc."
        name = f"focus {app[:24]}"
        rid = add_routine(
            name,
            trigger_kind="focus_app",
            trigger={"app": app},
            actions=actions,
        )
        return f"Routine #{rid} created — when {app} is frontmost: {action_text}."

    if not re.search(r"\b(at|@)\s*\d", low) and "every" not in low:
        return "Include a time — e.g. every weekday at 8 am daily briefing."

    hour, minute = _parse_time(low)
    weekdays = _parse_weekdays(low)
    actions = _parse_actions(raw)
    if not actions:
        return "I need at least one action — briefing, reflection, open loops, etc."

    name_m = re.search(r"(?:called|named)\s+([a-z0-9 _-]{2,32})", low)
    if name_m:
        name = name_m.group(1).strip()
    else:
        wd = "weekdays" if weekdays == [0, 1, 2, 3, 4] else "daily"
        name = f"{wd} {hour:02d}:{minute:02d}"

    rid = add_routine(
        name,
        trigger_kind="schedule",
        trigger={"hour": hour, "minute": minute, "weekdays": weekdays},
        actions=actions,
    )
    acts = ", ".join(a.get("type", "") for a in actions)
    return f"Routine #{rid} '{name}' at {hour}:{minute:02d} → {acts}."


def describe_routines_for_voice() -> str:
    routines = list_routines()
    if not routines:
        return "No routines yet. Say: every weekday at 8 am daily briefing."
    parts: list[str] = []
    for r in routines:
        status = "on" if r.enabled else "off"
        acts = ", ".join(a.get("type", "?") for a in r.actions)
        if r.trigger_kind == "schedule":
            h = int(r.trigger.get("hour", 0))
            m = int(r.trigger.get("minute", 0))
            parts.append(f"#{r.id} {r.name} ({status}) at {h}:{m:02d} → {acts}")
        elif r.trigger_kind == "focus_app":
            app = r.trigger.get("app", "?")
            parts.append(f"#{r.id} {r.name} ({status}) in {app} → {acts}")
        else:
            parts.append(f"#{r.id} {r.name} ({status}) → {acts}")
    return "Routines: " + "; ".join(parts)


def execute_action(action: dict[str, Any], *, speak_fn: Callable[[str], None]) -> str:
    kind = str(action.get("type") or "").strip().lower()
    if kind == "speak":
        text = str(action.get("text") or "").strip()
        if text:
            speak_fn(text)
        return text or "spoken"

    if kind == "briefing":
        from briefing import build_daily_briefing

        msg = build_daily_briefing()
        speak_fn(msg)
        return msg[:200]

    if kind == "reflection":
        from reflection import build_daily_reflection

        msg = build_daily_reflection()
        if msg:
            speak_fn(msg)
        return (msg or "reflection done")[:200]

    if kind == "open_loops":
        from open_loops import describe_for_voice

        msg = describe_for_voice(limit=4)
        speak_fn(msg)
        return msg[:200]

    if kind == "weekly_digest":
        from weekly_digest import build_weekly_digest

        msg = build_weekly_digest()
        if msg:
            speak_fn(msg)
        return (msg or "digest done")[:200]

    if kind == "calendar_today":
        from calendar_service import calendar_today_events

        events = calendar_today_events(limit=6)
        if not events:
            msg = "Nothing on your calendar today."
        else:
            bits = [f"{e.get('title', '?')}" for e in events[:4]]
            msg = "Today: " + "; ".join(bits)
        speak_fn(msg)
        return msg[:200]

    if kind == "glance_on":
        from glance_mode import start_glance_mode

        start_glance_mode(speak_fn)
        return "glance on"

    if kind == "glance_off":
        from glance_mode import stop_glance_mode

        stop_glance_mode()
        return "glance off"

    if kind == "homekit_scene":
        from smart_home import homekit_set_scene

        name = str(action.get("name") or "good night")
        res = homekit_set_scene(name)
        msg = res.get("message") or str(res)
        if res.get("ok"):
            speak_fn(msg)
        return msg[:200]

    if kind == "slack":
        from outgoing import slack_post

        text = str(action.get("text") or "")
        ok = slack_post(text)
        return "Slack sent." if ok else "Slack failed."

    return f"unknown action {kind}"


def run_routine(routine: Routine, *, speak_fn: Callable[[str], None], manual: bool = False) -> str:
    if not routine.enabled and not manual:
        return f"Routine #{routine.id} is disabled."
    results: list[str] = []
    for action in routine.actions:
        try:
            results.append(execute_action(action, speak_fn=speak_fn))
        except Exception as exc:
            results.append(f"error: {exc}")
    return f"Ran routine '{routine.name}': " + " | ".join(results)[:400]


def run_routine_by_id_or_name(target: str, *, speak_fn: Callable[[str], None]) -> str:
    t = (target or "").strip()
    if not t:
        return "Which routine?"
    routine: Optional[Routine] = None
    if t.isdigit():
        routine = get_routine(int(t))
    if routine is None:
        routine = find_routine_by_name(t)
    if routine is None:
        return f"No routine matching '{target}'."
    return run_routine(routine, speak_fn=speak_fn, manual=True)


def _schedule_fire_key(routine: Routine, now) -> str:
    return f"{routine.id}:{now.date().isoformat()}:{routine.trigger.get('hour')}:{routine.trigger.get('minute')}"


def _should_fire_schedule(routine: Routine, now) -> tuple[bool, str]:
    trig = routine.trigger
    hour = int(trig.get("hour", 0))
    minute = int(trig.get("minute", 0))
    weekdays = trig.get("weekdays") or list(range(7))
    if now.weekday() not in weekdays:
        return False, ""
    if now.hour != hour or now.minute != minute:
        return False, ""
    key = _schedule_fire_key(routine, now)
    if routine.last_fire_key == key:
        return False, ""
    return True, key


def _should_fire_focus_app(routine: Routine) -> tuple[bool, str]:
    app_needle = str(routine.trigger.get("app") or "").strip().lower()
    if not app_needle:
        return False, ""
    try:
        import awareness as aw

        app = aw.active_app() or {}
        name = (app.get("name") or "").lower()
        title = (app.get("window_title") or "").lower()
        bundle = (app.get("bundle_id") or "").lower()
    except Exception:
        return False, ""
    if app_needle not in name and app_needle not in title and app_needle not in bundle:
        return False, ""
    key = f"focus:{routine.id}:{app_needle}"
    if routine.last_fired_at and (time.time() - routine.last_fired_at) < 1800:
        return False, ""
    return True, key


def _tick() -> None:
    if not enabled() or _SPEAK_FN is None:
        return
    import datetime as dt

    now = dt.datetime.now()
    for routine in list_routines(include_disabled=False):
        fire = False
        fire_key = ""
        if routine.trigger_kind == "schedule":
            fire, fire_key = _should_fire_schedule(routine, now)
        elif routine.trigger_kind == "focus_app":
            fire, fire_key = _should_fire_focus_app(routine)

        if not fire:
            continue
        try:
            run_routine(routine, speak_fn=_SPEAK_FN, manual=False)
            _mark_fired(routine.id, fire_key)
        except Exception:
            pass


def start_routines_daemon(speak_fn: Callable[[str], None]) -> bool:
    global _THREAD, _SPEAK_FN
    if not enabled():
        return False
    if _STARTED.is_set():
        _SPEAK_FN = speak_fn
        return True
    _SPEAK_FN = speak_fn
    _STOP.clear()
    _STARTED.set()
    _THREAD = threading.Thread(target=_loop, name="jarvis-routines", daemon=True)
    _THREAD.start()
    print("[startup] Routines engine: active", flush=True)
    return True


def stop_routines_daemon() -> None:
    global _THREAD
    _STOP.set()
    _STARTED.clear()
    t = _THREAD
    if t and t.is_alive():
        t.join(timeout=2.0)
    _THREAD = None


def _loop() -> None:
    while not _STOP.is_set():
        try:
            _tick()
        except Exception:
            pass
        _STOP.wait(_tick_s())


def try_handle_routine_command(query: str, *, speak_fn: Callable[[str], None]) -> Optional[str]:
    q = (query or "").strip().lower()
    if not q:
        return None

    if q in ("list routines", "show routines", "my routines", "what routines"):
        return describe_routines_for_voice()

    if q.startswith("run routine "):
        return run_routine_by_id_or_name(q[len("run routine "):].strip(), speak_fn=speak_fn)

    if q.startswith("delete routine ") or q.startswith("remove routine "):
        for prefix in ("delete routine ", "remove routine "):
            if q.startswith(prefix):
                tail = q[len(prefix):].strip()
                break
        else:
            tail = ""
        if tail.isdigit():
            ok = delete_routine(int(tail))
            return f"Deleted routine #{tail}." if ok else f"No routine #{tail}."
        return "Say delete routine followed by the number."

    if q.startswith("disable routine "):
        tail = q[len("disable routine "):].strip()
        if tail.isdigit() and set_routine_enabled(int(tail), False):
            return f"Routine #{tail} disabled."
        return "Say disable routine followed by the number."

    if q.startswith("enable routine "):
        tail = q[len("enable routine "):].strip()
        if tail.isdigit() and set_routine_enabled(int(tail), True):
            return f"Routine #{tail} enabled."
        return "Say enable routine followed by the number."

    if q.startswith("create routine ") or q.startswith("add routine "):
        for prefix in ("create routine ", "add routine "):
            if q.startswith(prefix):
                body = query[len(prefix):].strip()
                break
        else:
            body = query
        return parse_and_create_routine(body)

    if q.startswith("every ") or q.startswith("when i") or q.startswith("when in"):
        return parse_and_create_routine(query)

    return None


__all__ = [
    "Routine",
    "add_routine",
    "delete_routine",
    "describe_routines_for_voice",
    "enabled",
    "execute_action",
    "list_routines",
    "parse_and_create_routine",
    "run_routine",
    "run_routine_by_id_or_name",
    "set_routine_enabled",
    "start_routines_daemon",
    "stop_routines_daemon",
    "try_handle_routine_command",
]
