"""Track unresolved commitments the user mentions in conversation.

Examples: "I still need to call the dentist", "I said I'd finish the deck",
"I haven't booked the flight yet". Surfaces gentle follow-ups via ambient
and weekly digest — distinct from reminders (no alarm time).
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DB_LOCK = threading.Lock()

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bi (?:still )?need to (.+)", re.I), "need"),
    (re.compile(r"\bi should (.+)", re.I), "should"),
    (re.compile(r"\bi have to (.+)", re.I), "have"),
    (re.compile(r"\bi (?:said i'?d|promised to|meant to|was going to) (.+)", re.I), "promised"),
    (re.compile(r"\bi haven'?t (.+?) yet\b", re.I), "haven't"),
    (re.compile(r"\bi forgot to (.+)", re.I), "forgot"),
    (re.compile(r"\bstill need (.+)", re.I), "still"),
]

_DONE_RE = re.compile(
    r"\b(done with|finished|completed|called|booked|sent|did)\b.{0,40}\b(.+)\b",
    re.I,
)


def _db_path() -> str:
    base = os.environ.get("JARVIS_DATA_DIR", "data")
    Path(base).mkdir(parents=True, exist_ok=True)
    return os.path.join(base, "jarvis_open_loops.sqlite")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_schema() -> None:
    with _DB_LOCK, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS open_loops (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL DEFAULT 'default',
                text        TEXT NOT NULL,
                kind        TEXT NOT NULL DEFAULT 'commitment',
                status      TEXT NOT NULL DEFAULT 'open',
                created_at  REAL NOT NULL,
                last_seen   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_loops_user_status
                ON open_loops(user_id, status, last_seen);
            """
        )


_ensure_schema()


def _user_id() -> str:
    try:
        from user_profiles import active_user

        return active_user() or "default"
    except Exception:
        return "default"


def _enabled() -> bool:
    return os.environ.get("JARVIS_OPEN_LOOPS", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _clean_payload(raw: str) -> str:
    t = (raw or "").strip().strip(" .,!?:;")
    t = re.sub(r"\s+", " ", t)
    if len(t) > 180:
        t = t[:177] + "..."
    return t


@dataclass
class OpenLoop:
    id: int
    text: str
    kind: str
    status: str
    created_at: float
    last_seen: float


def observe_utterance(text: str) -> list[OpenLoop]:
    """Extract commitments from ``text`` and upsert open loops."""
    if not _enabled():
        return []
    utterance = (text or "").strip()
    if not utterance:
        return []

    uid = _user_id()
    now = time.time()
    touched: list[OpenLoop] = []

    for pat, kind in _PATTERNS:
        m = pat.search(utterance)
        if not m:
            continue
        payload = _clean_payload(m.group(1))
        if len(payload) < 4:
            continue
        with _DB_LOCK, _conn() as c:
            row = c.execute(
                "SELECT id FROM open_loops WHERE user_id=? AND status='open' "
                "AND lower(text)=lower(?) LIMIT 1",
                (uid, payload),
            ).fetchone()
            if row:
                c.execute(
                    "UPDATE open_loops SET last_seen=? WHERE id=?",
                    (now, int(row["id"])),
                )
                loop_id = int(row["id"])
            else:
                cur = c.execute(
                    "INSERT INTO open_loops (user_id, text, kind, status, created_at, last_seen) "
                    "VALUES (?, ?, ?, 'open', ?, ?)",
                    (uid, payload, kind, now, now),
                )
                loop_id = int(cur.lastrowid)
        touched.append(
            OpenLoop(id=loop_id, text=payload, kind=kind, status="open",
                     created_at=now, last_seen=now)
        )

    dm = _DONE_RE.search(utterance)
    if dm:
        fragment = _clean_payload(dm.group(2) if dm.lastindex and dm.lastindex >= 2 else dm.group(0))
        if fragment:
            resolve_matching(fragment)
    return touched


def list_open_loops(*, limit: int = 12) -> list[OpenLoop]:
    uid = _user_id()
    with _DB_LOCK, _conn() as c:
        rows = c.execute(
            "SELECT * FROM open_loops WHERE user_id=? AND status='open' "
            "ORDER BY last_seen DESC LIMIT ?",
            (uid, int(limit)),
        ).fetchall()
    return [
        OpenLoop(
            id=int(r["id"]), text=r["text"], kind=r["kind"], status=r["status"],
            created_at=float(r["created_at"]), last_seen=float(r["last_seen"]),
        )
        for r in rows
    ]


def resolve_loop(loop_id: int) -> bool:
    uid = _user_id()
    with _DB_LOCK, _conn() as c:
        cur = c.execute(
            "UPDATE open_loops SET status='done' WHERE id=? AND user_id=?",
            (int(loop_id), uid),
        )
        return cur.rowcount > 0


def resolve_matching(fragment: str) -> int:
    needle = (fragment or "").strip().lower()
    if not needle:
        return 0
    uid = _user_id()
    n = 0
    with _DB_LOCK, _conn() as c:
        rows = c.execute(
            "SELECT id, text FROM open_loops WHERE user_id=? AND status='open'",
            (uid,),
        ).fetchall()
        for r in rows:
            hay = (r["text"] or "").lower()
            if needle in hay or hay in needle:
                c.execute("UPDATE open_loops SET status='done' WHERE id=?", (int(r["id"]),))
                n += 1
    return n


def due_followups(*, min_age_hours: float = 24.0, max_items: int = 2) -> list[OpenLoop]:
    if not _enabled():
        return []
    cutoff = time.time() - min_age_hours * 3600
    uid = _user_id()
    with _DB_LOCK, _conn() as c:
        rows = c.execute(
            "SELECT * FROM open_loops WHERE user_id=? AND status='open' "
            "AND created_at < ? ORDER BY last_seen ASC LIMIT ?",
            (uid, cutoff, int(max_items)),
        ).fetchall()
    return [
        OpenLoop(
            id=int(r["id"]), text=r["text"], kind=r["kind"], status=r["status"],
            created_at=float(r["created_at"]), last_seen=float(r["last_seen"]),
        )
        for r in rows
    ]


def format_followup(loop: OpenLoop) -> str:
    return f"Want me to help you {loop.text}?"


def describe_for_voice(limit: int = 6) -> str:
    loops = list_open_loops(limit=limit)
    if not loops:
        return "No open loops on my list."
    parts = [f"{i}. {l.text}" for i, l in enumerate(loops, 1)]
    return f"You have {len(loops)} open loop{'s' if len(loops) != 1 else ''}: " + "; ".join(parts)


__all__ = [
    "OpenLoop",
    "describe_for_voice",
    "due_followups",
    "format_followup",
    "list_open_loops",
    "observe_utterance",
    "resolve_loop",
    "resolve_matching",
]
