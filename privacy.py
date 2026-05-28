"""Privacy & trust: private mode, selective forgetting, confirmation gates.

Private mode
------------
When enabled, the assistant:
  - Skips writing user/assistant turns to episodic memory.
  - Skips writing actions to action_history.
  - Lowers TTS prominence (uses persona's quietest voice settings).
  - On disable, can optionally purge any turns/actions that slipped through
    via :func:`forget_recent_minutes`.

Selective forgetting
--------------------
- :func:`forget_recent_minutes(n)` removes episodic turns + action_history rows
  within the last N minutes.
- :func:`forget_today()` removes everything from today.

Confirmation gates
------------------
Use ``await_confirmation()`` to enqueue a high-risk action that needs a yes/no
from the user. The next utterance is intercepted by the voice loop and either
runs or cancels the action.
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# --------------------------------------------------------------------------- #
# Private mode state (process-global; small intentionally)
# --------------------------------------------------------------------------- #


@dataclass
class _PrivacyState:
    private: bool = False
    private_enabled_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = _PrivacyState()


def is_private() -> bool:
    return _state.private


def set_private(enabled: bool) -> None:
    with _state.lock:
        if enabled and not _state.private:
            _state.private_enabled_at = time.time()
        _state.private = bool(enabled)


def private_session_age_s() -> float:
    if not _state.private:
        return 0.0
    return time.time() - _state.private_enabled_at


# --------------------------------------------------------------------------- #
# Selective forgetting
# --------------------------------------------------------------------------- #


def forget_recent_minutes(minutes: int) -> dict:
    """Wipe episodic + action_history rows from the last ``minutes`` minutes."""
    minutes = max(1, int(minutes))
    cutoff_ts = time.time() - minutes * 60
    result = {"episodic_deleted": 0, "actions_deleted": 0,
              "threads_touched": 0, "errors": []}
    _wipe_episodic_since(cutoff_ts, result)
    _wipe_actions_since(cutoff_ts, result)
    return result


def forget_today() -> dict:
    start = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return forget_recent_minutes(int((time.time() - start.timestamp()) / 60) + 1)


def _wipe_episodic_since(cutoff_ts: float, result: dict) -> None:
    """Best-effort wipe across SQLite and Postgres backends."""
    try:
        import sqlite3

        from memory.episodic_memory import _db_path  # type: ignore[attr-defined]

        path = _db_path()
        if os.path.isfile(path):
            with sqlite3.connect(path) as c:
                cur = c.execute("DELETE FROM turns WHERE ts >= ?", (cutoff_ts,))
                result["episodic_deleted"] += int(cur.rowcount or 0)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"episodic: {exc}")


def _wipe_actions_since(cutoff_ts: float, result: dict) -> None:
    try:
        import sqlite3

        # action_history uses data/jarvis_actions.sqlite by convention.
        base = os.environ.get("JARVIS_DATA_DIR", "data")
        path = os.path.join(base, "jarvis_actions.sqlite")
        if os.path.isfile(path):
            with sqlite3.connect(path) as c:
                cur = c.execute("DELETE FROM actions WHERE ts >= ?", (cutoff_ts,))
                result["actions_deleted"] += int(cur.rowcount or 0)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"actions: {exc}")


def disable_private_and_purge() -> dict:
    """Turn off private mode, then purge anything that slipped through."""
    age_s = private_session_age_s()
    set_private(False)
    minutes = max(1, int(age_s // 60) + 1)
    return forget_recent_minutes(minutes)


# --------------------------------------------------------------------------- #
# Confirmation gate
# --------------------------------------------------------------------------- #


@dataclass
class PendingAction:
    label: str
    perform: Callable[[], Any]
    cancel: Optional[Callable[[], Any]] = None
    expires_at: float = 0.0
    payload: dict = field(default_factory=dict)


_pending: Optional[PendingAction] = None
_pending_lock = threading.Lock()


def await_confirmation(label: str, perform: Callable[[], Any], *,
                       cancel: Optional[Callable[[], Any]] = None,
                       expires_in_s: float = 60.0,
                       payload: Optional[dict] = None) -> PendingAction:
    """Enqueue an action; user must confirm or cancel via voice."""
    global _pending
    with _pending_lock:
        _pending = PendingAction(
            label=label, perform=perform, cancel=cancel,
            expires_at=time.time() + max(5.0, expires_in_s),
            payload=payload or {},
        )
    return _pending


def has_pending() -> bool:
    with _pending_lock:
        if _pending is None:
            return False
        if time.time() > _pending.expires_at:
            return False
        return True


def describe_pending() -> str:
    with _pending_lock:
        if _pending is None or time.time() > _pending.expires_at:
            return "No pending action."
        remaining = int(_pending.expires_at - time.time())
        return f"Pending: {_pending.label} (expires in {remaining}s)."


def resolve_pending(approve: bool) -> tuple[bool, str]:
    """Run or cancel the pending action. Returns (ran, message)."""
    global _pending
    with _pending_lock:
        action = _pending
        _pending = None
    if not action:
        return False, "No pending action."
    if time.time() > action.expires_at:
        return False, f"The pending '{action.label}' had expired."
    if approve:
        try:
            result = action.perform()
            return True, f"Done: {action.label}. {result if isinstance(result, str) else ''}".strip()
        except Exception as exc:  # noqa: BLE001
            return False, f"Failed: {exc}"
    if action.cancel:
        try:
            action.cancel()
        except Exception:
            pass
    return False, f"Cancelled: {action.label}."


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


def describe_privacy_state() -> str:
    bits = [f"private_mode={'on' if _state.private else 'off'}"]
    if _state.private:
        bits.append(f"age={int(private_session_age_s())}s")
    if has_pending():
        bits.append(describe_pending())
    return "; ".join(bits)


__all__ = [
    "PendingAction",
    "await_confirmation",
    "describe_pending",
    "describe_privacy_state",
    "disable_private_and_purge",
    "forget_recent_minutes",
    "forget_today",
    "has_pending",
    "is_private",
    "private_session_age_s",
    "resolve_pending",
    "set_private",
]
