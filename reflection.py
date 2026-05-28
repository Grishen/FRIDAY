"""Daily reflection — at end-of-day (or on demand), summarize what happened
and what FRIDAY learned about you.

Pulls from:
- Episodic memory (today's user + assistant turns).
- Topic threads (what's open, what got resolved).
- Action history (what was done / undone).
- Reminders fired today, calendar events.

The result is:
- Spoken as a 2-3 sentence end-of-day reflection (if invoked at runtime).
- Stored as a "note" in episodic memory with prefix ``reflection:`` so the next
  day's greeting can reference it.
- Optionally saved as a markdown file in ``knowledge_docs/_reflections/`` so
  it becomes part of long-term RAG.

API:
    build_daily_reflection() -> str
    speak_reflection(speak_fn)
    schedule_nightly_reflection(speak_fn, hour=22, minute=30)
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional


def _today_bounds(now: Optional[_dt.datetime] = None) -> tuple[_dt.datetime, _dt.datetime]:
    now = now or _dt.datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + _dt.timedelta(days=1)
    return start, end


def _collect_episodic_today() -> tuple[list[str], list[str]]:
    """Return (user_lines, assistant_lines) for today, newest last."""
    try:
        from memory.episodic_memory import memory_recent_rows
    except Exception:
        return [], []
    try:
        rows = memory_recent_rows(limit=400)
    except Exception:
        return [], []
    start, _ = _today_bounds()
    start_ts = start.timestamp()
    user_lines: list[str] = []
    assist_lines: list[str] = []
    for r in rows:
        ts = r.get("ts") if isinstance(r, dict) else None
        if ts is None:
            continue
        try:
            ts_v = float(ts)
        except (TypeError, ValueError):
            continue
        if ts_v < start_ts:
            continue
        role = (r.get("role") or "").lower()
        text = (r.get("text") or "").strip()
        if not text:
            continue
        if role == "user":
            user_lines.append(text)
        elif role == "assistant":
            assist_lines.append(text)
    return user_lines, assist_lines


def _collect_actions_today() -> list[str]:
    try:
        from action_history import list_recent_actions

        items = list_recent_actions(limit=100) or []
    except Exception:
        return []
    start, _ = _today_bounds()
    out: list[str] = []
    for a in items:
        try:
            ts = a.get("ts") if isinstance(a, dict) else None
            if ts is None:
                continue
            ts_v = float(ts)
            if ts_v < start.timestamp():
                continue
            kind = a.get("kind") or "action"
            payload = a.get("payload") or {}
            summary = payload.get("summary") or payload.get("title") or payload.get("message") or ""
            out.append(f"{kind}: {summary}" if summary else kind)
        except Exception:
            continue
    return out


def _collect_threads_summary() -> str:
    try:
        from topic_threads import list_threads

        open_threads = list_threads(status="open", limit=10) or []
    except Exception:
        return ""
    if not open_threads:
        return ""
    labels = [t.label for t in open_threads[:6]]
    return "Open threads: " + ", ".join(labels)


def _llm_synthesize(prompt: str) -> Optional[str]:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        sys_msg = (
            "You are FRIDAY, the user's personal assistant, writing a private "
            "end-of-day reflection in your own voice. Be specific to today's "
            "facts, warm but concise (2–3 sentences). Do not invent details. "
            "If nothing notable happened, say so honestly."
        )
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
        )
        return (completion.choices[0].message.content or "").strip()
    except Exception:
        return None


def build_daily_reflection() -> str:
    user_lines, assist_lines = _collect_episodic_today()
    actions = _collect_actions_today()
    threads_line = _collect_threads_summary()

    if not user_lines and not actions:
        return "It was a quiet day, Sir — no notable activity to reflect on."

    body_parts: list[str] = []
    body_parts.append(f"User said {len(user_lines)} thing(s) today.")
    if assist_lines:
        body_parts.append(f"I replied {len(assist_lines)} time(s).")
    if actions:
        body_parts.append("Actions: " + "; ".join(actions[:10]))
    if threads_line:
        body_parts.append(threads_line)
    if user_lines:
        body_parts.append("Sample user lines: " + " || ".join(user_lines[-6:]))
    raw_prompt = "\n".join(body_parts)

    synthesized = _llm_synthesize(raw_prompt)
    if synthesized:
        return synthesized

    # Template fallback (no LLM key).
    parts = [f"Today we had {len(user_lines)} turn{'s' if len(user_lines) != 1 else ''}."]
    if actions:
        parts.append(f"You ran {len(actions)} action{'s' if len(actions) != 1 else ''}.")
    if threads_line:
        parts.append(threads_line + ".")
    return " ".join(parts)


def persist_reflection(text: str) -> None:
    """Save reflection to episodic memory + a markdown file under knowledge_docs."""
    try:
        from memory.episodic_memory import memory_append_turn

        memory_append_turn("assistant", f"reflection:{text}")
    except Exception:
        pass
    base = os.environ.get("JARVIS_KNOWLEDGE_DIR", "knowledge_docs")
    out_dir = Path(base) / "_reflections"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = out_dir / f"{_dt.date.today().isoformat()}.md"
        with open(fname, "a", encoding="utf-8") as f:
            f.write(f"## {_dt.datetime.now().strftime('%H:%M')}\n\n{text}\n\n---\n\n")
    except Exception:
        pass


def speak_reflection(speak_fn: Callable[[str], None]) -> str:
    text = build_daily_reflection()
    if text:
        persist_reflection(text)
        try:
            speak_fn(text)
        except Exception:
            pass
    return text


# --------------------------------------------------------------------------- #
# Nightly scheduler
# --------------------------------------------------------------------------- #


_SCHEDULE_STOP = threading.Event()
_SCHEDULE_THREAD: Optional[threading.Thread] = None
_LAST_RUN_DATE: Optional[str] = None


def _schedule_loop(speak_fn: Callable[[str], None], hour: int, minute: int) -> None:
    global _LAST_RUN_DATE
    while not _SCHEDULE_STOP.is_set():
        now = _dt.datetime.now()
        today = now.date().isoformat()
        if (now.hour, now.minute) >= (hour, minute) and _LAST_RUN_DATE != today:
            try:
                speak_reflection(speak_fn)
            except Exception:
                pass
            _LAST_RUN_DATE = today
        _SCHEDULE_STOP.wait(60)


def schedule_nightly_reflection(speak_fn: Callable[[str], None], *,
                                 hour: int = 22, minute: int = 30) -> bool:
    global _SCHEDULE_THREAD
    if _SCHEDULE_THREAD and _SCHEDULE_THREAD.is_alive():
        return True
    _SCHEDULE_STOP.clear()
    t = threading.Thread(target=_schedule_loop, args=(speak_fn, hour, minute),
                         name="reflection-scheduler", daemon=True)
    _SCHEDULE_THREAD = t
    t.start()
    return True


def stop_reflection_scheduler() -> None:
    _SCHEDULE_STOP.set()
    global _SCHEDULE_THREAD
    t = _SCHEDULE_THREAD
    if t and t.is_alive():
        t.join(timeout=1.0)
    _SCHEDULE_THREAD = None


__all__ = [
    "build_daily_reflection",
    "persist_reflection",
    "schedule_nightly_reflection",
    "speak_reflection",
    "stop_reflection_scheduler",
]
