"""Multi-turn dialogue state + pronoun/referent resolution.

Tracks short-lived conversational context that lives between turns:

- ``last_action``  — most recent user-initiated effectful action
                      (reminder, calendar event, note, sent email/slack…)
- ``last_topic``   — short label of the last topical exchange
- ``pending_task`` — an in-progress multi-step task (e.g. "scheduling meeting,
                      need attendee and time")

Stored in-process; not persisted (a session is one process). When the user
says things like *"do that again"*, *"cancel it"*, *"send that to slack"*,
this module resolves the reference.
"""

from __future__ import annotations

import re
import time
from threading import Lock
from typing import Any, Optional

_state: dict[str, Any] = {
    "last_action": None,    # dict {kind, payload, undo_data, timestamp}
    "last_topic": None,     # short label
    "last_reply": None,     # str
    "pending_task": None,   # dict {name, prompt, slots}
}
_lock = Lock()


def remember_last_action(kind: str, payload: dict[str, Any], undo_data: dict[str, Any]) -> None:
    with _lock:
        _state["last_action"] = {
            "kind": kind,
            "payload": payload,
            "undo_data": undo_data,
            "timestamp": time.time(),
        }


def remember_last_topic(topic: str) -> None:
    with _lock:
        _state["last_topic"] = (topic or "").strip()[:80]


def remember_last_reply(reply: str) -> None:
    with _lock:
        _state["last_reply"] = (reply or "").strip()


def get_last_action() -> Optional[dict[str, Any]]:
    with _lock:
        return _state.get("last_action")


def get_last_topic() -> Optional[str]:
    with _lock:
        return _state.get("last_topic")


def get_last_reply() -> Optional[str]:
    with _lock:
        return _state.get("last_reply")


def open_task(name: str, slots: Optional[dict[str, Any]] = None, prompt: str = "") -> None:
    with _lock:
        _state["pending_task"] = {
            "name": name.strip(),
            "slots": dict(slots or {}),
            "prompt": prompt.strip(),
            "started_at": time.time(),
        }


def update_task_slot(key: str, value: Any) -> Optional[dict[str, Any]]:
    with _lock:
        task = _state.get("pending_task")
        if not task:
            return None
        task["slots"][key] = value
        return task


def get_pending_task() -> Optional[dict[str, Any]]:
    with _lock:
        return _state.get("pending_task")


def close_task() -> Optional[dict[str, Any]]:
    with _lock:
        t = _state.get("pending_task")
        _state["pending_task"] = None
        return t


# ---------- referent resolution ----------

_PRONOUN_RE = re.compile(
    r"\b(it|that|this|the (?:last )?(?:one|reminder|note|event|email|message))\b",
    re.I,
)


def utterance_references_previous(text: str) -> bool:
    return bool(_PRONOUN_RE.search(text or ""))


_RESOLUTION_RE = re.compile(
    r"\b(do that again|repeat that|say that again|cancel (?:it|that|the (?:last )?one)|"
    r"send (?:that|it) to slack|email (?:that|it) to me|undo (?:it|that))\b",
    re.I,
)


def resolve_simple_command(text: str) -> Optional[str]:
    """
    Map shorthand referent phrases to a canonical voice command string the
    rest of the loop can route normally. Returns ``None`` if no rewrite.
    """
    low = (text or "").strip().lower()
    if not low:
        return None
    m = _RESOLUTION_RE.search(low)
    if not m:
        return None
    hit = m.group(1)

    last = get_last_action()
    last_reply = get_last_reply()

    if hit in ("cancel it", "cancel that", "cancel the last one", "cancel the last reminder"):
        return "undo last"
    if hit in ("undo it", "undo that"):
        return "undo last"

    if hit in ("do that again", "repeat that"):
        if last_reply:
            return f"__REPLAY_REPLY__::{last_reply}"
        return None

    if hit == "say that again":
        if last_reply:
            return f"__REPLAY_REPLY__::{last_reply}"
        return None

    if hit in ("send that to slack", "send it to slack"):
        if last_reply:
            return f"slack {last_reply}"
        return None

    if hit in ("email that to me", "email it to me"):
        if last_reply:
            return f"email myself {last_reply}"
        return None

    return None


def describe_state_for_prompt() -> str:
    """Compact summary the brain prompt can include for continuity."""
    parts: list[str] = []
    last = get_last_action()
    if last:
        kind = last.get("kind")
        payload = last.get("payload") or {}
        label = payload.get("summary") or payload.get("title") or payload.get("message") or ""
        parts.append(f"last_action: {kind} — {label}")
    topic = get_last_topic()
    if topic:
        parts.append(f"last_topic: {topic}")
    pending = get_pending_task()
    if pending:
        slots = ", ".join(f"{k}={v}" for k, v in (pending.get("slots") or {}).items())
        parts.append(f"pending_task: {pending.get('name')} (slots: {slots or 'none'})")
    return "\n".join(parts)


__all__ = [
    "close_task",
    "describe_state_for_prompt",
    "get_last_action",
    "get_last_reply",
    "get_last_topic",
    "get_pending_task",
    "open_task",
    "remember_last_action",
    "remember_last_reply",
    "remember_last_topic",
    "resolve_simple_command",
    "update_task_slot",
    "utterance_references_previous",
]
