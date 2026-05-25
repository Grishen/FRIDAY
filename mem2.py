"""Episodic memory: rolling dialogue context + durable notes.

Storage order:

1. If ``DATABASE_URL`` (or ``POSTGRES_*``) resolves: Postgres table ``jarvis_episodic_memory``.
2. Else: SQLite ``data/jarvis_memory.sqlite`` (never requires a server).

Env:

- ``JARVIS_MEMORY_BACKEND`` — ``auto`` (default), ``postgres``, ``sqlite``
- ``JARVIS_MEMORY_LINES`` — rows to inject into the brain prompt (default 24)
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
_DATA = ROOT / "data"
_SQLITE_PATH = _DATA / "jarvis_memory.sqlite"

_PG_LOCK = threading.Lock()
_SQL_LOCK = threading.Lock()


def _memory_backend_pref() -> str:
    raw = os.environ.get("JARVIS_MEMORY_BACKEND", "auto").strip().lower()
    if raw not in {"auto", "postgres", "sqlite"}:
        return "auto"
    return raw


def _postgres_url_ready() -> bool:
    if os.environ.get("DATABASE_URL", "").strip():
        return True
    return bool(os.environ.get("POSTGRES_DB", "").strip())


def _use_postgres() -> bool:
    pref = _memory_backend_pref()
    if pref == "postgres":
        return True
    if pref == "sqlite":
        return False
    return _postgres_url_ready()


def memory_default_line_limit() -> int:
    raw = os.environ.get("JARVIS_MEMORY_LINES", "24").strip()
    try:
        n = int(raw)
    except ValueError:
        return 24
    return max(4, min(80, n))


def memory_fetch_block(*, max_lines: int | None = None, max_chars: int = 6000) -> str:
    rows = memory_recent_rows(limit=max_lines or memory_default_line_limit())
    if not rows:
        return ""
    parts: list[str] = []
    for role, text in rows:
        t = (text or "").strip().replace("\n", " ")
        if len(t) > 500:
            t = t[:497] + "..."
        parts.append(f"[{role}] {t}")
    # Keep most recent contiguous block within max_chars by dropping oldest lines.
    out: list[str] = []
    total = 0
    for p in reversed(parts):
        total += len(p) + 1
        if total > max_chars:
            break
        out.append(p)
    out.reverse()
    return "\n".join(out)


def memory_append_turn(role: str, content: str) -> None:
    role_clean = role.strip().lower()
    if role_clean not in ("user", "assistant", "note"):
        role_clean = "note"
    text = (content or "").strip()
    if not text:
        return
    if _use_postgres():
        _pg_append(role_clean, text)
        return
    _sqlite_append(role_clean, text)


def memory_recent_rows(*, limit: int) -> list[tuple[str, str]]:
    if _use_postgres():
        return _pg_recent(limit)
    return _sqlite_recent(limit)


# --- SQLite ---
def _sqlite_ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS episodic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )


def _sqlite_append(role: str, content: str) -> None:
    import time as _time

    _DATA.mkdir(parents=True, exist_ok=True)
    with _SQL_LOCK:
        conn = sqlite3.connect(_SQLITE_PATH)
        try:
            _sqlite_ensure(conn)
            conn.execute(
                "INSERT INTO episodic_memory (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, _time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def _sqlite_recent(limit: int) -> list[tuple[str, str]]:
    with _SQL_LOCK:
        conn = sqlite3.connect(_SQLITE_PATH)
        try:
            _sqlite_ensure(conn)
            cur = conn.execute(
                """
                SELECT role, content FROM (
                    SELECT id, role, content FROM episodic_memory
                    ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (max(1, limit),),
            )
            rows = [(str(a), str(b)) for (a, b) in cur.fetchall()]
            return rows
        finally:
            conn.close()


# --- Postgres ---
def _pg_connect():
    """Reuse same URL rules as kb postgres module."""
    from knowledge.postgres_kb import connect as pg_connect

    return pg_connect()


def _ensure_pg_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jarvis_episodic_memory (
                id BIGSERIAL PRIMARY KEY,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'note')),
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS jarvis_memory_created_idx
            ON jarvis_episodic_memory (id DESC)
            """
        )
    conn.commit()


def _pg_append(role: str, content: str) -> None:
    import time as _sleep_mod

    with _PG_LOCK:
        backoff = 0.25
        for attempt in range(5):
            try:
                conn = _pg_connect()
                try:
                    _ensure_pg_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO jarvis_episodic_memory (role, content)
                            VALUES (%s, %s)
                            """,
                            (role, content),
                        )
                    conn.commit()
                finally:
                    conn.close()
                return
            except Exception:
                _sleep_mod.sleep(backoff)
                backoff *= 2


def _pg_recent(limit: int) -> list[tuple[str, str]]:
    with _PG_LOCK:
        conn = _pg_connect()
        try:
            _ensure_pg_table(conn)
            take = max(1, limit)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT role, content FROM (
                        SELECT id, role, content FROM jarvis_episodic_memory
                        ORDER BY id DESC LIMIT %s
                    ) snap ORDER BY snap.id ASC
                    """,
                    (take,),
                )
                return [(str(r[0]), str(r[1])) for r in cur.fetchall()]
        finally:
            conn.close()


def prune_memory_notes(*, keep_last: int = 200) -> None:
    """Optional maintenance: drop old rows keeping the last *keep_last* total rows."""
    if _use_postgres():
        with _PG_LOCK:
            conn = _pg_connect()
            try:
                _ensure_pg_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM jarvis_episodic_memory
                        WHERE id < (
                          SELECT MIN(id) FROM (
                            SELECT id FROM jarvis_episodic_memory
                            ORDER BY id DESC LIMIT %s
                          ) sub
                        )
                        """,
                        (max(1, keep_last),),
                    )
                conn.commit()
            finally:
                conn.close()
        return

    # SQLite prune
    with _SQL_LOCK:
        conn = sqlite3.connect(_SQLITE_PATH)
        try:
            _sqlite_ensure(conn)
            conn.execute(
                """
                DELETE FROM episodic_memory
                WHERE id NOT IN (
                  SELECT id FROM episodic_memory
                  ORDER BY id DESC LIMIT ?
                )
                """,
                (max(1, keep_last),),
            )
            conn.commit()
        finally:
            conn.close()
