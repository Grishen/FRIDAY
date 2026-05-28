"""Action history + undo for reversible assistant actions.

Tracks recent reversible operations (set reminder, create calendar event,
save knowledge note, capture profile fact) in a SQLite ledger so the user
can say things like "undo", "undo last reminder", or "undo last note".

Each entry stores:

- ``kind``       — short label ("reminder", "calendar", "note", "profile")
- ``payload``    — JSON describing what happened (for display)
- ``undo_data``  — JSON instructing how to reverse it
- ``status``     — 'active' | 'undone' | 'failed'

This module performs the undo itself for kinds it owns; ``record_action``
is called from the producers (reminders, calendar, etc.) but never from
this module to avoid circular imports.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
_DATA = ROOT / "data"
_DB_PATH = _DATA / "jarvis_actions.sqlite"
_LOCK = threading.Lock()

_VALID_KINDS = {"reminder", "calendar", "note", "profile"}


def _connect() -> sqlite3.Connection:
    _DATA.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB_PATH)


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            undo_data TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS action_log_kind_idx ON action_log (kind, status, id DESC)"
    )


def record_action(
    *,
    kind: str,
    payload: dict[str, Any],
    undo_data: dict[str, Any],
) -> int:
    # Honor private mode — high-trust requirement.
    try:
        from privacy import is_private as _is_private

        if _is_private():
            return 0
    except Exception:
        pass
    k = (kind or "").strip().lower()
    if k not in _VALID_KINDS:
        k = "note"
    with _LOCK:
        conn = _connect()
        try:
            _ensure(conn)
            cur = conn.execute(
                """
                INSERT INTO action_log (kind, payload, undo_data, status, created_at)
                VALUES (?, ?, ?, 'active', ?)
                """,
                (
                    k,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(undo_data, ensure_ascii=False),
                    time.time(),
                ),
            )
            conn.commit()
            action_id = int(cur.lastrowid or 0)
        finally:
            conn.close()
    try:
        from dialogue_state import remember_last_action

        remember_last_action(k, payload, undo_data)
    except Exception:
        pass
    return action_id


def _fetch_latest_active(kind: Optional[str]) -> Optional[tuple[int, str, dict, dict]]:
    with _LOCK:
        conn = _connect()
        try:
            _ensure(conn)
            if kind:
                row = conn.execute(
                    """
                    SELECT id, kind, payload, undo_data FROM action_log
                    WHERE status='active' AND kind=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (kind.lower(),),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id, kind, payload, undo_data FROM action_log
                    WHERE status='active'
                    ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
            if not row:
                return None
            try:
                payload = json.loads(row[2])
            except Exception:
                payload = {}
            try:
                undo = json.loads(row[3])
            except Exception:
                undo = {}
            return int(row[0]), str(row[1]), payload, undo
        finally:
            conn.close()


def _mark_status(action_id: int, status: str) -> None:
    with _LOCK:
        conn = _connect()
        try:
            _ensure(conn)
            conn.execute(
                "UPDATE action_log SET status=? WHERE id=?",
                (status, int(action_id)),
            )
            conn.commit()
        finally:
            conn.close()


def list_recent_actions(*, limit: int = 10) -> list[dict[str, Any]]:
    with _LOCK:
        conn = _connect()
        try:
            _ensure(conn)
            rows = conn.execute(
                """
                SELECT id, kind, payload, status, created_at FROM action_log
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        finally:
            conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            payload = json.loads(r[2])
        except Exception:
            payload = {}
        out.append(
            {
                "id": int(r[0]),
                "kind": str(r[1]),
                "payload": payload,
                "status": str(r[3]),
                "created_at": float(r[4]),
            }
        )
    return out


# ---------- undo executors ----------

def _undo_reminder(undo: dict[str, Any]) -> str:
    rid = int(undo.get("reminder_id", 0))
    if rid <= 0:
        return "No reminder id to undo."
    from reminders import cancel_reminder

    if cancel_reminder(rid):
        return f"Cancelled reminder #{rid}."
    return f"Reminder #{rid} was already fired or cancelled."


def _undo_note(undo: dict[str, Any]) -> str:
    file_path = str(undo.get("file_path", "")).strip()
    if not file_path:
        return "No knowledge note path recorded."
    p = Path(file_path)
    if not p.is_file():
        return f"Knowledge note already missing: {p.name}"
    try:
        p.unlink()
    except Exception as exc:  # noqa: BLE001
        return f"Failed to delete note: {exc}"
    return f"Deleted knowledge note: {p.name}"


def _undo_profile(undo: dict[str, Any]) -> str:
    note_text = str(undo.get("note_text", "")).strip()
    if not note_text:
        return "No profile note recorded."
    from memory.episodic_memory import memory_forget_notes_containing

    removed = memory_forget_notes_containing(note_text)
    return f"Removed {removed} profile note(s) matching '{note_text}'."


def _undo_calendar(undo: dict[str, Any]) -> str:
    # AppleScript deletion is intentionally not automated for safety; show a hint.
    title = str(undo.get("title", "")).strip()
    when = str(undo.get("start", "")).strip()
    if title:
        return (
            f"Calendar event '{title}' (at {when}) was not auto-deleted for safety. "
            "Open Calendar.app to remove it manually if needed."
        )
    return "No calendar event details recorded for undo."


_UNDO_TABLE = {
    "reminder": _undo_reminder,
    "note": _undo_note,
    "profile": _undo_profile,
    "calendar": _undo_calendar,
}


def undo_last(kind: Optional[str] = None) -> str:
    """Undo the most recent active action (optionally restricted to a kind)."""
    target = _fetch_latest_active(kind.lower() if kind else None)
    if target is None:
        if kind:
            return f"No recent {kind} action to undo."
        return "No recent action to undo."
    action_id, k, payload, undo = target
    handler = _UNDO_TABLE.get(k)
    if not handler:
        _mark_status(action_id, "failed")
        return f"No undo handler for action kind '{k}'."
    try:
        msg = handler(undo)
        _mark_status(action_id, "undone")
        label = payload.get("summary") or payload.get("title") or payload.get("message") or ""
        return f"{msg} ({k} #{action_id}{': ' + label if label else ''})"
    except Exception as exc:  # noqa: BLE001
        _mark_status(action_id, "failed")
        return f"Undo failed: {exc}"


def describe_recent_actions(*, limit: int = 5) -> str:
    items = list_recent_actions(limit=limit)
    if not items:
        return "No tracked actions yet."
    lines = []
    for it in items:
        p = it["payload"] or {}
        label = p.get("summary") or p.get("title") or p.get("message") or ""
        lines.append(
            f"#{it['id']} {it['kind']} [{it['status']}]" + (f": {label}" if label else "")
        )
    return "Recent actions: " + " | ".join(lines)


__all__ = [
    "describe_recent_actions",
    "list_recent_actions",
    "record_action",
    "undo_last",
]
