"""Ambient / proactive assistant daemon.

A background thread that periodically inspects the world (reminders, calendar,
idle time, time-of-day shifts, low battery, weather changes) and surfaces only
*signal*, never noise. Anti-spam rules are baked in:

- Each check is rate-limited (cannot fire more often than its cooldown).
- Quiet hours are honored (default 22:00–07:00 local).
- Each "thing" is announced at most once per natural unit (e.g. each calendar
  event surfaced exactly once at the chosen lead time).
- "Do not disturb" mode (set via ``set_dnd(True)``) silences everything except
  emergencies.

Registering checks::

    register_check(
        name="pre_meeting",
        fn=callable_returning_str_or_none,
        cooldown_s=60,
        critical=False,
    )

The default install registers: idle_checkin, time_of_day_shift, pre_meeting,
due_reminders_soon. Bring your own with ``register_check`` before starting.

API:
    start_ambient_daemon(speak_fn) — non-blocking; idempotent
    stop_ambient_daemon()
    set_dnd(True/False)
    mark_user_active() — call from your voice loop on every user utterance
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


@dataclass
class _Check:
    name: str
    fn: Callable[[], Optional[str]]
    cooldown_s: float
    critical: bool = False
    last_ran_at: float = 0.0
    last_fired_at: float = 0.0
    fail_count: int = 0


@dataclass
class _State:
    checks: dict[str, _Check] = field(default_factory=dict)
    fired_keys: set[str] = field(default_factory=set)  # de-dupe per-natural-unit
    session_fired: set[str] = field(default_factory=set)  # never repeat in one session
    snooze_until: dict[str, float] = field(default_factory=dict)  # category -> unix expiry
    last_user_activity_at: float = field(default_factory=time.time)
    last_announce_at: float = 0.0
    dnd: bool = False
    paused: bool = False
    speak_fn: Optional[Callable[[str], None]] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = _State()


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def _quiet_hours_range() -> tuple[int, int]:
    raw = os.environ.get("JARVIS_AMBIENT_QUIET", "22-7").strip()
    try:
        a, b = raw.split("-")
        return int(a) % 24, int(b) % 24
    except Exception:
        return 22, 7


def _is_quiet_now(now: Optional[_dt.datetime] = None) -> bool:
    now = now or _dt.datetime.now()
    start, end = _quiet_hours_range()
    h = now.hour
    if start == end:
        return False
    if start < end:
        return start <= h < end
    # wraps midnight, e.g. 22-7
    return h >= start or h < end


def _ambient_enabled() -> bool:
    raw = os.environ.get("JARVIS_AMBIENT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _min_announce_gap_s() -> float:
    try:
        return float(os.environ.get("JARVIS_AMBIENT_MIN_GAP", "60"))
    except (TypeError, ValueError):
        return 60.0


def _tick_s() -> float:
    try:
        return max(2.0, float(os.environ.get("JARVIS_AMBIENT_TICK", "20")))
    except (TypeError, ValueError):
        return 20.0


# --------------------------------------------------------------------------- #
# Public control
# --------------------------------------------------------------------------- #


def register_check(name: str, fn: Callable[[], Optional[str]], *,
                   cooldown_s: float = 60, critical: bool = False) -> None:
    with _state.lock:
        _state.checks[name] = _Check(name=name, fn=fn, cooldown_s=cooldown_s, critical=critical)


def unregister_check(name: str) -> None:
    with _state.lock:
        _state.checks.pop(name, None)


def set_dnd(enabled: bool) -> None:
    _state.dnd = bool(enabled)


def is_dnd() -> bool:
    return _state.dnd


def set_paused(paused: bool) -> None:
    _state.paused = bool(paused)


def mark_user_active() -> None:
    _state.last_user_activity_at = time.time()


def seconds_idle() -> float:
    return time.time() - _state.last_user_activity_at


def has_fired(key: str) -> bool:
    return key in _state.fired_keys


def mark_fired(key: str) -> None:
    _state.fired_keys.add(key)


def reset_fired() -> None:
    _state.fired_keys.clear()


def reset_session() -> None:
    """Clear per-session de-dupe (call at voice session start)."""
    _state.session_fired.clear()


def snooze(category: str, seconds: float) -> None:
    """Silence a category of ambient nudges for ``seconds``."""
    cat = (category or "all").strip().lower() or "all"
    try:
        secs = max(60.0, float(seconds))
    except (TypeError, ValueError):
        secs = 3600.0
    _state.snooze_until[cat] = time.time() + secs


def is_snoozed(category: str = "all") -> bool:
    now = time.time()
    cat = (category or "all").strip().lower() or "all"
    # Expire stale entries.
    stale = [k for k, until in _state.snooze_until.items() if until <= now]
    for k in stale:
        _state.snooze_until.pop(k, None)
    if _state.snooze_until.get("all", 0) > now:
        return True
    return _state.snooze_until.get(cat, 0) > now


def parse_snooze_command(text: str) -> Optional[tuple[str, float]]:
    """
    Parse phrases like 'leave me alone for an hour', 'not now for 30 minutes',
    'snooze ambient until tomorrow'. Returns (category, seconds) or None.
    """
    low = (text or "").lower().strip()
    if not low:
        return None
    triggers = (
        "leave me alone", "not now", "stop nudging", "quiet for",
        "snooze ambient", "snooze check", "snooze check-ins", "do not disturb for",
        "dnd for", "pause nudges for",
    )
    if not any(t in low for t in triggers):
        return None

    seconds = 3600.0  # default 1 hour
    m = re.search(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|h)\b", low)
    if m:
        n = float(m.group(1))
        unit = m.group(2)
        if unit.startswith(("sec",)):
            seconds = n
        elif unit.startswith(("min",)):
            seconds = n * 60
        else:
            seconds = n * 3600
    elif "half an hour" in low or "30 minutes" in low:
        seconds = 1800.0
    elif "rest of the day" in low or "until tonight" in low:
        seconds = 6 * 3600.0

    category = "all"
    if "meeting" in low:
        category = "pre_meeting"
    elif "reminder" in low:
        category = "due_reminders_soon"
    elif "idle" in low or "check" in low:
        category = "idle_checkin"
    return category, max(60.0, seconds)


def _prefer_question(msg: str) -> str:
    """Rephrase statements as gentle questions when appropriate."""
    if os.environ.get("JARVIS_AMBIENT_QUESTIONS", "1").strip().lower() in ("0", "false", "no", "off"):
        return msg
    m = (msg or "").strip()
    if not m or m.endswith("?"):
        return m
    # Already a question starter.
    if re.match(r"^(want|would|should|shall|can i|may i|ready for)\b", m, re.I):
        return m if m.endswith("?") else m + "?"
    # Statement nudges → question form.
    replacements = (
        (r"^Still around, Sir\?", "Still around? Want me to read the morning briefing?"),
        (r"^Good morning, Sir\. Ready when you are\.$", "Good morning — want your briefing?"),
        (r"^Heads up, Sir — (.+)\.$", r"Heads up — \1. Want a quick prep summary?"),
        (r"^Reminder coming up at (.+), Sir: (.+)\.$", r"Reminder at \1: \2 — want me to repeat that?"),
    )
    for pat, repl in replacements:
        if re.match(pat, m):
            return re.sub(pat, repl, m)
    if m.endswith("."):
        core = m[:-1]
        if len(core) < 120 and not core.lower().startswith(("battery", "heads up")):
            return f"Want me to help with {core[0].lower()}{core[1:]}?"
    return m


def _session_key(check_name: str, msg: str) -> str:
    return f"session:{check_name}:{hash(msg) & 0xFFFF_FFFF}"


# --------------------------------------------------------------------------- #
# Built-in checks
# --------------------------------------------------------------------------- #


def _check_idle_checkin() -> Optional[str]:
    """If the user has been silent for IDLE_MIN minutes during active hours, prompt gently."""
    if is_snoozed("idle_checkin"):
        return None
    try:
        idle_min = float(os.environ.get("JARVIS_AMBIENT_IDLE_MIN", "45"))
    except (TypeError, ValueError):
        idle_min = 45.0
    if seconds_idle() < idle_min * 60:
        return None
    now = _dt.datetime.now()
    if _is_quiet_now(now):
        return None
    bucket = f"idle:{int(time.time() // 3600)}"
    if has_fired(bucket):
        return None
    mark_fired(bucket)
    hour = now.hour
    if 5 <= hour < 12:
        return _prefer_question("Want me to read your morning briefing?")
    if 12 <= hour < 17:
        return _prefer_question("Anything I can line up for the afternoon?")
    if 17 <= hour < 21:
        return _prefer_question("Want help winding down this evening?")
    return None


def _check_time_of_day_shift() -> Optional[str]:
    """Announce when we cross morning / afternoon / evening boundaries (max once per shift)."""
    now = _dt.datetime.now()
    if _is_quiet_now(now):
        return None
    hour = now.hour
    if hour < 5:
        return None
    if 5 <= hour < 12:
        shift = "morning"
    elif 12 <= hour < 17:
        shift = "afternoon"
    elif 17 <= hour < 21:
        shift = "evening"
    else:
        shift = "night"
    today = now.strftime("%Y-%m-%d")
    key = f"shift:{today}:{shift}"
    if has_fired(key):
        return None
    mark_fired(key)
    # Only speak the shift if the user has been *active* recently — otherwise
    # idle_checkin handles them.
    if seconds_idle() > 600:  # 10 min
        return None
    greetings = {
        "morning": _prefer_question("Good morning — want your briefing?"),
        "afternoon": _prefer_question("Want a quick afternoon check-in?"),
        "evening": _prefer_question("Want help wrapping up the day?"),
        "night": "Late hours — let me know if I can help you wind down.",
    }
    return greetings.get(shift)


def _check_pre_meeting() -> Optional[str]:
    """5 minutes before a calendar event, brief the user."""
    if is_snoozed("pre_meeting"):
        return None
    try:
        from calendar_service import calendar_available, calendar_upcoming_events
    except Exception:
        return None
    if not calendar_available():
        return None
    try:
        lead_min = int(os.environ.get("JARVIS_AMBIENT_MEETING_LEAD_MIN", "5"))
    except (TypeError, ValueError):
        lead_min = 5
    try:
        events = calendar_upcoming_events(hours=2) or []
    except Exception:
        return None
    now = _dt.datetime.now()
    lead = _dt.timedelta(minutes=lead_min)
    for ev in events[:8]:
        try:
            start = ev.get("start") if isinstance(ev, dict) else None
            if not start:
                continue
            if isinstance(start, str):
                start_dt = _parse_dt(start)
                if not start_dt:
                    continue
            else:
                start_dt = start
            delta = start_dt - now
            if _dt.timedelta(0) <= delta <= lead:
                title = (ev.get("title") if isinstance(ev, dict) else None) or "your next event"
                key = f"premeet:{start_dt.isoformat()}:{title}"
                if has_fired(key):
                    continue
                mark_fired(key)
                mins = max(1, int(delta.total_seconds() // 60))
                try:
                    from meeting_prep import prep_line_for_event

                    line = prep_line_for_event(title, minutes_until=mins)
                    if line:
                        return _prefer_question(line)
                except Exception:
                    pass
                return _prefer_question(
                    f"give you a heads-up — {title} in about {mins} minute{'s' if mins != 1 else ''}"
                )
        except Exception:
            continue
    return None


def _check_due_reminders_soon() -> Optional[str]:
    """Mention reminders due in the next 5 minutes once each."""
    if is_snoozed("due_reminders_soon"):
        return None
    try:
        from reminders import list_pending_reminders
    except Exception:
        return None
    try:
        items = list_pending_reminders() or []
    except Exception:
        return None
    now = _dt.datetime.now()
    horizon = _dt.timedelta(minutes=5)
    upcoming: list[tuple[str, str]] = []
    for r in items[:30]:
        try:
            due_raw = r.get("due") if isinstance(r, dict) else None
            if not due_raw:
                continue
            due = _parse_dt(due_raw) if isinstance(due_raw, str) else due_raw
            if not due:
                continue
            delta = due - now
            if _dt.timedelta(0) <= delta <= horizon:
                key = f"rem:{r.get('id')}:{due.isoformat()}"
                if has_fired(key):
                    continue
                mark_fired(key)
                upcoming.append((r.get("message", "your reminder"), due.strftime("%H:%M")))
        except Exception:
            continue
    if not upcoming:
        return None
    if len(upcoming) == 1:
        msg, t = upcoming[0]
        return _prefer_question(f"remind you at {t} — {msg}")
    return _prefer_question(f"mention your {len(upcoming)} upcoming reminders")


def _check_battery_low() -> Optional[str]:
    """If running on macOS, warn at 20% / 10% / 5% (once each per discharge)."""
    try:
        import platform_services  # type: ignore
    except Exception:
        return None
    try:
        pct = platform_services.battery_percent()
    except Exception:
        return None
    if pct is None:
        return None
    for threshold in (5, 10, 20):
        if pct <= threshold:
            key = f"batt:{threshold}"
            if has_fired(key):
                return None
            # Reset higher thresholds when crossing a lower one so we re-warn next charge cycle later.
            mark_fired(key)
            return f"Battery at {int(pct)} percent, Sir."
    # If we recharged past 30%, reset thresholds so future drops re-warn.
    if pct >= 30:
        for threshold in (5, 10, 20):
            _state.fired_keys.discard(f"batt:{threshold}")
    return None


def _parse_dt(s: str) -> Optional[_dt.datetime]:
    """Tolerant ISO/SQL datetime parser."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return _dt.datetime.fromisoformat(s)
    except Exception:
        return None


def _check_topic_callback() -> Optional[str]:
    """Once per quiet stretch, offer to resume an open thread."""
    try:
        from topic_threads import due_callbacks, format_callback
    except Exception:
        return None
    if seconds_idle() < 60 * 20:  # don't interrupt active conversation
        return None
    now = _dt.datetime.now()
    if _is_quiet_now(now):
        return None
    callbacks = due_callbacks()
    if not callbacks:
        return None
    t = callbacks[0]
    key = f"callback:{t.id}:{int(time.time() // 86400)}"
    if has_fired(key):
        return None
    mark_fired(key)
    return format_callback(t)


def _check_open_loops() -> Optional[str]:
    try:
        from open_loops import due_followups, format_followup

        loops = due_followups(min_age_hours=24.0, max_items=1)
        if not loops:
            return None
        loop = loops[0]
        key = f"openloop:{loop.id}:{int(time.time() // 86400)}"
        if has_fired(key):
            return None
        mark_fired(key)
        return _prefer_question(format_followup(loop).replace("Want me to help you ", "help you "))
    except Exception:
        return None


def _check_weekly_digest() -> Optional[str]:
    """Monday morning-ish weekly recap (once per week)."""
    now = _dt.datetime.now()
    if now.weekday() != 0 or _is_quiet_now(now):  # Monday
        return None
    if now.hour < 8 or now.hour > 11:
        return None
    key = f"weekly:{now.strftime('%Y-%W')}"
    if has_fired(key):
        return None
    mark_fired(key)
    try:
        from weekly_digest import build_weekly_digest

        digest = build_weekly_digest()
        if digest:
            return _prefer_question(f"share your weekly digest — {digest[:180]}")
    except Exception:
        return None
    return None


def _check_environment_coach() -> Optional[str]:
    try:
        from env_coach import environment_suggestion

        return environment_suggestion()
    except Exception:
        return None


def _check_post_meeting() -> Optional[str]:
    try:
        from post_meeting import check_post_meeting_prompt

        line = check_post_meeting_prompt()
        if line:
            return _prefer_question(line)
    except Exception:
        return None
    return None


def _install_default_checks() -> None:
    register_check("time_of_day_shift", _check_time_of_day_shift, cooldown_s=300)
    register_check("idle_checkin", _check_idle_checkin, cooldown_s=600)
    register_check("pre_meeting", _check_pre_meeting, cooldown_s=30, critical=True)
    register_check("due_reminders_soon", _check_due_reminders_soon, cooldown_s=30, critical=True)
    register_check("battery_low", _check_battery_low, cooldown_s=60)
    register_check("topic_callback", _check_topic_callback, cooldown_s=1800)
    register_check("environment_coach", _check_environment_coach, cooldown_s=120)
    register_check("open_loops", _check_open_loops, cooldown_s=3600)
    register_check("weekly_digest", _check_weekly_digest, cooldown_s=86400)
    register_check("post_meeting", _check_post_meeting, cooldown_s=300)


# --------------------------------------------------------------------------- #
# Daemon loop
# --------------------------------------------------------------------------- #


def _can_speak_now(critical: bool) -> bool:
    if _state.paused:
        return False
    if is_snoozed("all") and not critical:
        return False
    if _state.dnd and not critical:
        return False
    if (time.time() - _state.last_announce_at) < _min_announce_gap_s():
        return False
    return True


def _loop() -> None:
    while not _state.stop_event.is_set():
        try:
            now = time.time()
            with _state.lock:
                checks = list(_state.checks.values())
            for check in checks:
                if _state.stop_event.is_set():
                    break
                if (now - check.last_ran_at) < check.cooldown_s:
                    continue
                check.last_ran_at = now
                if is_snoozed(check.name) and not check.critical:
                    continue
                if not _can_speak_now(check.critical):
                    continue
                try:
                    msg = check.fn()
                except Exception:
                    check.fail_count += 1
                    if os.environ.get("JARVIS_AMBIENT_DEBUG") == "1":
                        traceback.print_exc()
                    continue
                if not msg:
                    continue
                sk = _session_key(check.name, msg)
                if sk in _state.session_fired:
                    continue
                _state.session_fired.add(sk)
                msg = _prefer_question(msg)
                if _state.speak_fn:
                    try:
                        _state.speak_fn(msg)
                        check.last_fired_at = time.time()
                        _state.last_announce_at = time.time()
                    except Exception:
                        if os.environ.get("JARVIS_AMBIENT_DEBUG") == "1":
                            traceback.print_exc()
        except Exception:
            if os.environ.get("JARVIS_AMBIENT_DEBUG") == "1":
                traceback.print_exc()
        _state.stop_event.wait(_tick_s())


def start_ambient_daemon(speak_fn: Callable[[str], None]) -> bool:
    """Start the ambient thread. Idempotent. Returns True if started, False if disabled."""
    if not _ambient_enabled():
        return False
    if _state.thread and _state.thread.is_alive():
        _state.speak_fn = speak_fn
        return True
    reset_session()
    _install_default_checks()
    _state.speak_fn = speak_fn
    _state.stop_event.clear()
    _state.thread = threading.Thread(target=_loop, name="ambient-daemon", daemon=True)
    _state.thread.start()
    return True


def stop_ambient_daemon() -> None:
    _state.stop_event.set()
    t = _state.thread
    if t and t.is_alive():
        t.join(timeout=1.0)
    _state.thread = None


def describe_status() -> str:
    with _state.lock:
        checks = list(_state.checks.keys())
    return (f"Ambient: thread={'alive' if (_state.thread and _state.thread.is_alive()) else 'stopped'}, "
            f"dnd={_state.dnd}, paused={_state.paused}, "
            f"idle={int(seconds_idle())}s, checks={','.join(checks) or 'none'}, "
            f"quiet_hours={_quiet_hours_range()}")


__all__ = [
    "describe_status",
    "has_fired",
    "is_dnd",
    "is_snoozed",
    "mark_fired",
    "mark_user_active",
    "parse_snooze_command",
    "register_check",
    "reset_fired",
    "reset_session",
    "seconds_idle",
    "set_dnd",
    "set_paused",
    "snooze",
    "start_ambient_daemon",
    "stop_ambient_daemon",
    "unregister_check",
]
