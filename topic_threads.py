"""Topic threading & emotional callbacks.

Tracks the user's ongoing "threads" (projects, people, recurring topics) so
FRIDAY can resume them later — "How did the talk with Sarah go?", "Want to
continue the marketing plan we were working on yesterday?".

Storage: SQLite at ``data/jarvis_threads.sqlite`` (auto-created). Each thread
has a stable id, label, kind (project|person|task|interest|other), status
(open|stale|resolved), salience score, last_seen ts, and a rolling list of
notes pulled from episodic memory.

Update flow:
- ``observe_utterance(text)`` is called for each user turn. It extracts
  candidate thread anchors (proper nouns, project-style phrases, emotional
  context) using a lightweight regex pass, optionally enriched by an LLM call
  when ``OPENAI_API_KEY`` is set.
- Threads are merged with existing entries when a high-overlap match is found.
- Stale threads auto-decay; resolved threads (user said "done with X") stick
  around but won't be surfaced proactively.

Callback flow:
- ``due_callbacks(now)`` returns threads worth following up on right now
  (open + last_seen older than a configurable interval + still salient).
- ``format_callback(thread)`` produces a single voice-friendly line.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def _db_path() -> str:
    base = os.environ.get("JARVIS_DATA_DIR", "data")
    Path(base).mkdir(parents=True, exist_ok=True)
    return os.path.join(base, "jarvis_threads.sqlite")


_DB_LOCK = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema() -> None:
    with _DB_LOCK, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS threads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL DEFAULT 'default',
                label       TEXT NOT NULL,
                kind        TEXT NOT NULL DEFAULT 'other',
                status      TEXT NOT NULL DEFAULT 'open',
                salience    REAL NOT NULL DEFAULT 1.0,
                created_at  REAL NOT NULL,
                last_seen   REAL NOT NULL,
                notes_json  TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_threads_user_status
                ON threads(user_id, status, last_seen);
            CREATE INDEX IF NOT EXISTS idx_threads_label
                ON threads(label);
            """
        )


_ensure_schema()


def _current_user() -> str:
    try:
        from user_profiles import active_user

        return active_user() or "default"
    except Exception:
        return "default"


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "without", "from", "by", "at", "as", "is", "are", "was", "were",
    "be", "been", "being", "do", "did", "does", "have", "has", "had", "this",
    "that", "these", "those", "it", "its", "i", "me", "my", "you", "your",
    "we", "our", "they", "them", "he", "she", "his", "her", "what", "when",
    "where", "why", "how", "who", "whom", "okay", "ok", "please", "sir",
}

_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*\b")
_PROJECT_RE = re.compile(
    r"\b(?:the\s+)?([a-z][a-z0-9\-]+(?:\s[a-z][a-z0-9\-]+){0,3})\s+"
    r"(?:project|task|plan|launch|migration|sprint|deal|trip|meeting|interview|talk)\b",
    re.IGNORECASE,
)
_ACTIVITY_VERBS = (
    "meeting", "lunch", "dinner", "call", "interview", "talk", "chat",
    "session", "review", "demo", "presentation",
)


def _candidate_labels(text: str) -> list[tuple[str, str]]:
    """Return list of (label, kind) candidates from a free-form utterance."""
    text = (text or "").strip()
    if not text:
        return []
    out: list[tuple[str, str]] = []

    # Proper nouns → likely people (or product/project names).
    for m in _PROPER_NOUN_RE.finditer(text):
        token = m.group(0).strip()
        if token.lower() in _STOPWORDS:
            continue
        if len(token) < 2:
            continue
        kind = "person" if any(v in text.lower() for v in _ACTIVITY_VERBS) else "other"
        # Looser heuristic: short bare proper nouns ≈ person.
        if token.split() and len(token.split()) <= 2 and token[0].isupper():
            kind = "person" if kind == "person" else "other"
        out.append((token, kind))

    # Project-style phrases.
    for m in _PROJECT_RE.finditer(text):
        label = m.group(0).strip(" .,!?:;")
        out.append((label.lower(), "project"))

    # De-duplicate while preserving order.
    seen = set()
    dedup: list[tuple[str, str]] = []
    for lab, kind in out:
        key = (lab.lower(), kind)
        if key in seen:
            continue
        seen.add(key)
        dedup.append((lab, kind))
    return dedup[:5]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


@dataclass
class Thread:
    id: int
    label: str
    kind: str
    status: str
    salience: float
    last_seen: float
    created_at: float
    notes: list[str] = field(default_factory=list)


def _row_to_thread(row: sqlite3.Row) -> Thread:
    try:
        notes = json.loads(row["notes_json"]) or []
    except Exception:
        notes = []
    return Thread(
        id=int(row["id"]),
        label=row["label"],
        kind=row["kind"],
        status=row["status"],
        salience=float(row["salience"] or 0.0),
        last_seen=float(row["last_seen"] or 0.0),
        created_at=float(row["created_at"] or 0.0),
        notes=notes,
    )


def list_threads(*, status: Optional[str] = "open", limit: int = 25) -> list[Thread]:
    uid = _current_user()
    with _DB_LOCK, _conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM threads WHERE user_id = ? AND status = ? "
                "ORDER BY salience DESC, last_seen DESC LIMIT ?",
                (uid, status, int(limit)),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM threads WHERE user_id = ? "
                "ORDER BY last_seen DESC LIMIT ?",
                (uid, int(limit)),
            ).fetchall()
    return [_row_to_thread(r) for r in rows]


def find_thread(label: str) -> Optional[Thread]:
    """Case-insensitive longest-substring match for ``label``."""
    uid = _current_user()
    needle = (label or "").strip().lower()
    if not needle:
        return None
    with _DB_LOCK, _conn() as c:
        rows = c.execute(
            "SELECT * FROM threads WHERE user_id = ? "
            "ORDER BY salience DESC LIMIT 200",
            (uid,),
        ).fetchall()
    for r in rows:
        if needle == r["label"].lower():
            return _row_to_thread(r)
    for r in rows:
        lab = r["label"].lower()
        if needle in lab or lab in needle:
            return _row_to_thread(r)
    return None


def upsert_thread(label: str, *, kind: str = "other", note: str = "",
                  bump_salience: float = 0.5) -> Thread:
    uid = _current_user()
    label = (label or "").strip()
    if not label:
        raise ValueError("label required")
    now = time.time()
    existing = find_thread(label)
    with _DB_LOCK, _conn() as c:
        if existing:
            notes = existing.notes[-19:] + ([note] if note else [])
            new_salience = min(10.0, existing.salience + bump_salience)
            c.execute(
                "UPDATE threads SET last_seen=?, salience=?, notes_json=?, kind=? "
                "WHERE id=?",
                (now, new_salience, json.dumps(notes),
                 kind if kind != "other" else existing.kind, existing.id),
            )
            updated = Thread(
                id=existing.id, label=existing.label,
                kind=kind if kind != "other" else existing.kind,
                status=existing.status, salience=new_salience,
                last_seen=now, created_at=existing.created_at, notes=notes,
            )
            return updated
        notes = [note] if note else []
        cur = c.execute(
            "INSERT INTO threads (user_id, label, kind, status, salience, "
            "created_at, last_seen, notes_json) VALUES (?, ?, ?, 'open', ?, ?, ?, ?)",
            (uid, label, kind, max(1.0, bump_salience * 2), now, now, json.dumps(notes)),
        )
        return Thread(
            id=int(cur.lastrowid), label=label, kind=kind, status="open",
            salience=max(1.0, bump_salience * 2), created_at=now, last_seen=now,
            notes=notes,
        )


def resolve_thread(label_or_id: str | int) -> Optional[Thread]:
    uid = _current_user()
    with _DB_LOCK, _conn() as c:
        if isinstance(label_or_id, int):
            row = c.execute(
                "SELECT * FROM threads WHERE id=? AND user_id=?",
                (label_or_id, uid),
            ).fetchone()
        else:
            t = find_thread(str(label_or_id))
            row = c.execute("SELECT * FROM threads WHERE id=?",
                            (t.id,)).fetchone() if t else None
        if not row:
            return None
        c.execute("UPDATE threads SET status='resolved' WHERE id=?", (int(row["id"]),))
    return _row_to_thread(row)


def forget_thread(label_or_id: str | int) -> bool:
    uid = _current_user()
    with _DB_LOCK, _conn() as c:
        if isinstance(label_or_id, int):
            cur = c.execute("DELETE FROM threads WHERE id=? AND user_id=?",
                            (label_or_id, uid))
        else:
            t = find_thread(str(label_or_id))
            if not t:
                return False
            cur = c.execute("DELETE FROM threads WHERE id=? AND user_id=?",
                            (t.id, uid))
        return cur.rowcount > 0


def observe_utterance(text: str) -> list[Thread]:
    """Extract thread candidates from ``text`` and upsert them. Returns the touched threads."""
    touched: list[Thread] = []
    for label, kind in _candidate_labels(text):
        try:
            touched.append(upsert_thread(label, kind=kind, note=text[:200]))
        except Exception:
            continue
    return touched


def decay_threads(*, stale_after_days: float = 7.0) -> int:
    """Mark old, low-salience open threads as 'stale'. Returns count changed."""
    cutoff = time.time() - stale_after_days * 86400
    with _DB_LOCK, _conn() as c:
        cur = c.execute(
            "UPDATE threads SET status='stale' "
            "WHERE status='open' AND last_seen < ? AND salience < 3.0",
            (cutoff,),
        )
        return cur.rowcount


def due_callbacks(*, min_age_hours: float = 18.0, max_items: int = 3) -> list[Thread]:
    """Return open threads worth surfacing right now."""
    cutoff = time.time() - min_age_hours * 3600
    uid = _current_user()
    with _DB_LOCK, _conn() as c:
        rows = c.execute(
            "SELECT * FROM threads WHERE user_id=? AND status='open' "
            "AND last_seen < ? AND salience >= 1.5 "
            "ORDER BY salience DESC, last_seen ASC LIMIT ?",
            (uid, cutoff, int(max_items)),
        ).fetchall()
    return [_row_to_thread(r) for r in rows]


def format_callback(thread: Thread) -> str:
    if thread.kind == "person":
        return f"How did your {thread.label} thing go, Sir?"
    if thread.kind == "project":
        return f"Want to pick up the {thread.label} again, Sir?"
    return f"We left off on {thread.label} — want to continue?"


def describe_threads_for_voice(limit: int = 5) -> str:
    threads = list_threads(status="open", limit=limit)
    if not threads:
        return "No open threads right now, Sir."
    parts = [f"{t.label} ({t.kind})" for t in threads]
    return f"You have {len(threads)} open thread{'s' if len(threads) != 1 else ''}: " + ", ".join(parts) + "."


__all__ = [
    "Thread",
    "decay_threads",
    "describe_threads_for_voice",
    "due_callbacks",
    "find_thread",
    "forget_thread",
    "format_callback",
    "list_threads",
    "observe_utterance",
    "resolve_thread",
    "upsert_thread",
]
