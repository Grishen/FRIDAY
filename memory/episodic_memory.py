"""Episodic memory: rolling dialogue context + durable notes.

Storage order:

1. If Postgres is configured (``DATABASE_URL`` or typical ``POSTGRES_*`` vars): table
   ``jarvis_episodic_memory`` (requires ``CREATE TABLE`` privileges).
2. Otherwise: SQLite at ``data/jarvis_memory.sqlite``.

Env:

- ``JARVIS_MEMORY_BACKEND`` — ``auto`` (default), ``postgres``, ``sqlite``
- ``JARVIS_MEMORY_LINES`` — rows injected into brain context (default 24)
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DATA = ROOT / "data"
_SQLITE_PATH = _DATA / "jarvis_memory.sqlite"

_PG_LOCK = threading.Lock()
_SQL_LOCK = threading.Lock()
_TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")
_PROFILE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bmy name is ([a-z][a-z .'-]{1,40})\b", re.IGNORECASE), "name"),
    (
        re.compile(r"\bi(?:'m| am) ([a-z][a-z .'-]{1,40})\b", re.IGNORECASE),
        "identity",
    ),
    (
        re.compile(r"\bi live in ([a-z0-9 ,.'-]{2,60})\b", re.IGNORECASE),
        "location",
    ),
    (
        re.compile(r"\bi work as (?:an? )?([a-z0-9 ,.'-]{2,60})\b", re.IGNORECASE),
        "work",
    ),
    (
        re.compile(r"\bmy birthday is ([a-z0-9 ,/-]{2,30})\b", re.IGNORECASE),
        "birthday",
    ),
    (
        re.compile(r"\bi (?:like|love|enjoy) ([a-z0-9 ,.'-]{2,80})\b", re.IGNORECASE),
        "preference",
    ),
    (
        re.compile(r"\bi (?:prefer|usually prefer) ([a-z0-9 ,.'-]{2,80})\b", re.IGNORECASE),
        "preference",
    ),
]


def _memory_backend_pref() -> str:
    raw = os.environ.get("JARVIS_MEMORY_BACKEND", "auto").strip().lower()
    if raw not in {"auto", "postgres", "sqlite"}:
        return "auto"
    return raw


def _postgres_configured() -> bool:
    if os.environ.get("DATABASE_URL", "").strip():
        return True
    if os.environ.get("POSTGRES_HOST", "").strip() and os.environ.get("POSTGRES_DB", "").strip():
        return True
    return False


def _use_postgres() -> bool:
    pref = _memory_backend_pref()
    if pref == "postgres":
        return True
    if pref == "sqlite":
        return False
    return _postgres_configured()


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


def _tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if len(token) > 2 and token.lower() not in {"the", "and", "for", "with"}
    }


def _looks_like_profile_note(text: str) -> bool:
    return text.lower().startswith("profile:")


def memory_auto_capture_user_profile(user_text: str) -> list[str]:
    """Extract simple user profile/event facts and store as note rows."""
    utterance = (user_text or "").strip()
    if not utterance:
        return []
    rows = memory_recent_rows(limit=220)
    existing_notes = {
        content.strip().lower() for role, content in rows if role == "note" and content.strip()
    }
    captured: list[str] = []
    for pattern, field in _PROFILE_PATTERNS:
        match = pattern.search(utterance)
        if not match:
            continue
        value = re.sub(r"\s+", " ", match.group(1)).strip(" .,!?:;")
        if not value:
            continue
        note = f"profile:{field}={value}"
        if note.lower() in existing_notes:
            continue
        memory_append_turn("note", note)
        existing_notes.add(note.lower())
        captured.append(note)
    # Capture explicit "remember ..." lines as durable events.
    low = utterance.lower()
    if "remember" in low and len(utterance) > 20:
        note = f"event: {utterance[:240]}"
        if note.lower() not in existing_notes:
            memory_append_turn("note", note)
            captured.append(note)
    return captured


def memory_build_context_for_prompt(
    *,
    query: str,
    recent_lines: int | None = None,
    candidate_pool: int = 260,
    max_chars: int = 7000,
) -> str:
    """
    Build richer prompt memory:
    - profile notes (durable)
    - relevant older memories by token overlap with current query
    - most recent conversation rows
    """
    recent_block = memory_fetch_block(
        max_lines=recent_lines or memory_default_line_limit(),
        max_chars=max_chars // 2,
    )
    rows = memory_recent_rows(limit=max(80, candidate_pool))
    query_tokens = _tokenize(query)
    profile_notes: list[str] = []
    scored: list[tuple[int, str, str]] = []
    for role, text in rows:
        clean = (text or "").strip().replace("\n", " ")
        if not clean:
            continue
        if _looks_like_profile_note(clean):
            profile_notes.append(clean)
            continue
        row_tokens = _tokenize(clean)
        overlap = len(query_tokens.intersection(row_tokens))
        if overlap:
            scored.append((overlap, role, clean))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = scored[:8]

    chunks: list[str] = []
    if profile_notes:
        unique_profiles = list(dict.fromkeys(profile_notes))[-8:]
        chunks.append("Known user profile facts:\n" + "\n".join(f"- {p}" for p in unique_profiles))
    if picked:
        rel_lines = [f"- [{role}] {text}" for _, role, text in picked]
        chunks.append("Relevant older memories:\n" + "\n".join(rel_lines))
    if recent_block:
        chunks.append("Recent conversation:\n" + recent_block)
    out = "\n\n".join(chunks).strip()
    return out[:max_chars]


def memory_recent_rows(*, limit: int) -> list[tuple[str, str]]:
    if _use_postgres():
        return _pg_recent(limit)
    return _sqlite_recent(limit)


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
    _DATA.mkdir(parents=True, exist_ok=True)
    with _SQL_LOCK:
        conn = sqlite3.connect(_SQLITE_PATH)
        try:
            _sqlite_ensure(conn)
            conn.execute(
                "INSERT INTO episodic_memory (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, time.time()),
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
                ) AS snap
                ORDER BY snap.id ASC
                """,
                (max(1, limit),),
            )
            return [(str(a), str(b)) for (a, b) in cur.fetchall()]
        finally:
            conn.close()


def _pg_connect():
    """Plain SQL connection (avoid pgvector registration on every episodic append)."""
    from knowledge.postgres_kb import connect_plain

    return connect_plain(autocommit=False)


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
            ON jarvis_episodic_memory (created_at DESC)
            """
        )
    conn.commit()


def _pg_append(role: str, content: str) -> None:
    with _PG_LOCK:
        backoff = 0.25
        for _ in range(5):
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
                time.sleep(backoff)
                backoff *= 2


def _pg_recent(limit: int) -> list[tuple[str, str]]:
    with _PG_LOCK:
        conn = _pg_connect()
        try:
            _ensure_pg_table(conn)
            take = max(1, limit)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT snap.role, snap.content FROM (
                        SELECT id, role, content FROM jarvis_episodic_memory
                        ORDER BY id DESC
                        LIMIT %s
                    ) AS snap
                    ORDER BY snap.id ASC
                    """,
                    (take,),
                )
                return [(str(r[0]), str(r[1])) for r in cur.fetchall()]
        finally:
            conn.close()


def prune_memory(*, keep_last: int = 200) -> None:
    """Delete old rows beyond the newest *keep_last* (optional housekeeping)."""
    k = max(10, keep_last)
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
                                ORDER BY id DESC
                                LIMIT %s
                            ) keepers
                        )
                        """,
                        (k,),
                    )
                conn.commit()
            finally:
                conn.close()
        return

    with _SQL_LOCK:
        conn = sqlite3.connect(_SQLITE_PATH)
        try:
            _sqlite_ensure(conn)
            conn.execute(
                """
                DELETE FROM episodic_memory
                WHERE id NOT IN (
                    SELECT id FROM episodic_memory ORDER BY id DESC LIMIT ?
                )
                """,
                (k,),
            )
            conn.commit()
        finally:
            conn.close()
