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
    """Best-effort write. Never raises — memory must never break the user's command.

    Honors privacy mode: when private mode is on, the turn is *not* persisted.
    """
    try:
        from privacy import is_private as _is_private

        if _is_private():
            return
    except Exception:
        pass
    try:
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
    except Exception as exc:
        print(f"[memory] append failed (non-fatal): {exc}")


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
        try:
            from action_history import record_action

            record_action(
                kind="profile",
                payload={"summary": note},
                undo_data={"note_text": note},
            )
        except Exception:
            pass
    # Capture explicit "remember ..." lines as durable events.
    low = utterance.lower()
    if "remember" in low and len(utterance) > 20:
        note = f"event: {utterance[:240]}"
        if note.lower() not in existing_notes:
            memory_append_turn("note", note)
            captured.append(note)
            try:
                from action_history import record_action

                record_action(
                    kind="profile",
                    payload={"summary": note[:160]},
                    undo_data={"note_text": note[:240]},
                )
            except Exception:
                pass
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
    summary_notes: list[str] = []
    scored: list[tuple[int, str, str]] = []
    for role, text in rows:
        clean = (text or "").strip().replace("\n", " ")
        if not clean:
            continue
        if _looks_like_profile_note(clean):
            profile_notes.append(clean)
            continue
        if clean.lower().startswith(_SUMMARY_PREFIX):
            summary_notes.append(clean[len(_SUMMARY_PREFIX) :].strip())
            continue
        row_tokens = _tokenize(clean)
        overlap = len(query_tokens.intersection(row_tokens))
        salience = memory_salience_score(role, clean)
        composite = overlap * 2.0 + min(2.0, salience)
        if composite >= 1.0:
            scored.append((composite, role, clean))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = scored[:8]

    chunks: list[str] = []
    if profile_notes:
        unique_profiles = list(dict.fromkeys(profile_notes))[-8:]
        chunks.append("Known user profile facts:\n" + "\n".join(f"- {p}" for p in unique_profiles))
    try:
        from relationship_memory import traits_for_prompt

        traits_block = traits_for_prompt()
        if traits_block:
            chunks.append(traits_block)
    except Exception:
        pass
    try:
        from mood_trajectory import trajectory_for_prompt

        traj = trajectory_for_prompt()
        if traj:
            chunks.append(traj)
    except Exception:
        pass
    if summary_notes:
        unique_summaries = list(dict.fromkeys(summary_notes))[-4:]
        chunks.append(
            "Long-term conversation summaries (oldest → newest):\n"
            + "\n\n".join(unique_summaries)
        )

    recall_hits = memory_detect_relevant_past(query, max_hits=2)
    if recall_hits:
        chunks.append(
            "Proactive recall (the user is likely revisiting something from earlier — "
            "briefly mention you remember it if it helps continuity):\n"
            + "\n".join(f"- {h}" for h in recall_hits)
        )

    if picked:
        rel_lines = [f"- [{role}] {text}" for _, role, text in picked]
        chunks.append("Relevant older memories:\n" + "\n".join(rel_lines))
    if recent_block:
        chunks.append("Recent conversation:\n" + recent_block)
    out = "\n\n".join(chunks).strip()
    return out[:max_chars]


def memory_recent_rows(*, limit: int) -> list[tuple[str, str]]:
    """Best-effort read. Never raises; returns ``[]`` on backend errors."""
    try:
        if _use_postgres():
            return _pg_recent(limit)
        return _sqlite_recent(limit)
    except Exception as exc:
        print(f"[memory] recent_rows failed (non-fatal): {exc}")
        return []


def _sqlite_ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS episodic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'default'
        )
        """
    )
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(episodic_memory)").fetchall()}
        if "user_id" not in cols:
            conn.execute(
                "ALTER TABLE episodic_memory ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
            )
    except sqlite3.OperationalError:
        pass


def _current_user_id() -> str:
    try:
        from user_profiles import active_user

        return active_user()
    except Exception:
        return "default"


def _quarantine_corrupt_sqlite(reason: str) -> None:
    """Move a non-SQLite or unreadable memory file out of the way and start fresh."""
    try:
        if _SQLITE_PATH.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = _SQLITE_PATH.with_name(f"{_SQLITE_PATH.name}.corrupt-{stamp}")
            try:
                _SQLITE_PATH.rename(backup)
                print(
                    f"[memory] quarantined corrupt SQLite ({reason}): "
                    f"{_SQLITE_PATH.name} -> {backup.name}"
                )
            except OSError:
                # Last-resort: unlink (some FS rename failures)
                try:
                    _SQLITE_PATH.unlink()
                    print(f"[memory] deleted corrupt SQLite ({reason}): {_SQLITE_PATH.name}")
                except OSError:
                    pass
    except Exception:
        pass


def _sqlite_open() -> sqlite3.Connection:
    """
    Open the episodic memory DB, auto-recovering if the file is not a valid SQLite
    database (e.g. truncated, garbage-written, or wrong format).
    """
    _DATA.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(_SQLITE_PATH)
        # Light probe — fails fast on "file is not a database".
        conn.execute("PRAGMA schema_version").fetchone()
        return conn
    except sqlite3.DatabaseError as exc:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass
        _quarantine_corrupt_sqlite(str(exc))
        return sqlite3.connect(_SQLITE_PATH)


def _sqlite_append(role: str, content: str) -> None:
    uid = _current_user_id()
    with _SQL_LOCK:
        try:
            conn = _sqlite_open()
        except Exception as exc:
            print(f"[memory] sqlite open failed, dropping write: {exc}")
            return
        try:
            try:
                _sqlite_ensure(conn)
                conn.execute(
                    "INSERT INTO episodic_memory (role, content, created_at, user_id) VALUES (?, ?, ?, ?)",
                    (role, content, time.time(), uid),
                )
                conn.commit()
            except sqlite3.DatabaseError as exc:
                conn.close()
                _quarantine_corrupt_sqlite(str(exc))
                # Retry once on a fresh file.
                conn = sqlite3.connect(_SQLITE_PATH)
                _sqlite_ensure(conn)
                conn.execute(
                    "INSERT INTO episodic_memory (role, content, created_at, user_id) VALUES (?, ?, ?, ?)",
                    (role, content, time.time(), uid),
                )
                conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass


def _sqlite_recent(limit: int) -> list[tuple[str, str]]:
    uid = _current_user_id()
    with _SQL_LOCK:
        try:
            conn = _sqlite_open()
        except Exception as exc:
            print(f"[memory] sqlite open failed, returning empty recent rows: {exc}")
            return []
        try:
            try:
                _sqlite_ensure(conn)
                cur = conn.execute(
                    """
                    SELECT role, content FROM (
                        SELECT id, role, content FROM episodic_memory
                        WHERE COALESCE(user_id, 'default') IN (?, 'default')
                        ORDER BY id DESC LIMIT ?
                    ) AS snap
                    ORDER BY snap.id ASC
                    """,
                    (uid, max(1, limit)),
                )
                return [(str(a), str(b)) for (a, b) in cur.fetchall()]
            except sqlite3.DatabaseError as exc:
                conn.close()
                _quarantine_corrupt_sqlite(str(exc))
                return []
        finally:
            try:
                conn.close()
            except Exception:
                pass


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
                created_at TIMESTAMPTZ DEFAULT NOW(),
                user_id TEXT NOT NULL DEFAULT 'default'
            )
            """
        )
        cur.execute(
            """
            ALTER TABLE jarvis_episodic_memory
            ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'default'
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS jarvis_memory_created_idx
            ON jarvis_episodic_memory (created_at DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS jarvis_memory_user_idx
            ON jarvis_episodic_memory (user_id, id DESC)
            """
        )
    conn.commit()


def _pg_append(role: str, content: str) -> None:
    uid = _current_user_id()
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
                            INSERT INTO jarvis_episodic_memory (role, content, user_id)
                            VALUES (%s, %s, %s)
                            """,
                            (role, content, uid),
                        )
                    conn.commit()
                finally:
                    conn.close()
                return
            except Exception:
                time.sleep(backoff)
                backoff *= 2


def _pg_recent(limit: int) -> list[tuple[str, str]]:
    uid = _current_user_id()
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
                        WHERE COALESCE(user_id, 'default') IN (%s, 'default')
                        ORDER BY id DESC
                        LIMIT %s
                    ) AS snap
                    ORDER BY snap.id ASC
                    """,
                    (uid, take),
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


_PROFILE_NOTE_RE = re.compile(r"^profile:([^=]+)=(.*)$", re.IGNORECASE)
_SUMMARY_PREFIX = "summary:"


def _summarize_threshold() -> int:
    raw = os.environ.get("JARVIS_MEMORY_SUMMARIZE_AFTER", "60").strip()
    try:
        n = int(raw)
    except ValueError:
        return 60
    return max(20, min(400, n))


def _summarize_block_size() -> int:
    raw = os.environ.get("JARVIS_MEMORY_SUMMARIZE_BATCH", "40").strip()
    try:
        n = int(raw)
    except ValueError:
        return 40
    return max(10, min(200, n))


def _count_unsummarized_turns(rows: list[tuple[str, str]]) -> int:
    """Count user/assistant turns since the most recent stored summary note."""
    count = 0
    for role, content in reversed(rows):
        if role == "note" and (content or "").strip().lower().startswith(_SUMMARY_PREFIX):
            break
        if role in ("user", "assistant"):
            count += 1
    return count


def _llm_summarize(text: str) -> str:
    """Best-effort LLM summary; returns empty string on any failure."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return ""
    try:
        from openai import OpenAI
    except ImportError:
        return ""
    try:
        client = OpenAI(api_key=key)
        model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Compress the following voice-assistant conversation excerpt into a "
                        "compact long-term memory note for future recall. Focus on: user "
                        "identity facts, preferences, ongoing projects, decisions, commitments, "
                        "and any explicit 'remember' items. Drop chit-chat. Output under 8 "
                        "short bullet points or 6 sentences total. No preamble."
                    ),
                },
                {"role": "user", "content": text[:14000]},
            ],
            temperature=0.2,
        )
        msg = getattr(completion.choices[0].message, "content", None) or ""
        return msg.strip()
    except Exception:
        return ""


def maybe_summarize_old_turns(*, force: bool = False) -> str:
    """
    If unsummarized user/assistant turns exceed the threshold, ask the LLM to
    compress the oldest batch into a durable ``summary:`` note. Returns the
    summary content (or empty string if nothing was done).
    """
    rows = memory_recent_rows(limit=500)
    unsummarized = _count_unsummarized_turns(rows)
    threshold = _summarize_threshold()
    if not force and unsummarized < threshold:
        return ""

    batch_size = _summarize_block_size()
    convo_rows = [
        (role, content) for role, content in rows if role in ("user", "assistant")
    ]
    if len(convo_rows) < max(10, batch_size // 2):
        return ""

    # Take the oldest *batch_size* conversation rows for summarization.
    batch = convo_rows[:batch_size]
    text_block = "\n".join(f"[{role}] {content}" for role, content in batch)
    summary = _llm_summarize(text_block)
    if not summary:
        # Fallback: keep last 3 user statements as a coarse summary if LLM unavailable.
        users = [c for r, c in batch if r == "user"][-3:]
        if not users:
            return ""
        summary = "Recent user statements: " + " | ".join(u[:140] for u in users)

    stored = f"{_SUMMARY_PREFIX} {summary[:1600]}"
    memory_append_turn("note", stored)
    return stored


_PROACTIVE_RECALL_THRESHOLD = 3


def memory_detect_relevant_past(
    query: str,
    *,
    max_rows: int = 320,
    max_hits: int = 3,
    min_overlap: int = _PROACTIVE_RECALL_THRESHOLD,
) -> list[str]:
    """
    Return short snippets of older memory rows strongly overlapping the
    current utterance — used for proactive recall nudges.

    Strong overlap = at least *min_overlap* shared content words (after a
    stoplist), excluding the most recent 6 conversation rows to avoid echoing
    the user back to themselves.
    """
    q_tokens = _tokenize(query)
    if len(q_tokens) < 2:
        return []
    rows = memory_recent_rows(limit=max_rows)
    if not rows:
        return []
    pool = rows[:-6] if len(rows) > 10 else rows
    scored: list[tuple[int, str, str]] = []
    for role, content in pool:
        text = (content or "").strip().replace("\n", " ")
        if not text:
            continue
        # Skip durable profile rows — they're already in the system prompt.
        if text.lower().startswith("profile:"):
            continue
        r_tokens = _tokenize(text)
        overlap = len(q_tokens.intersection(r_tokens))
        if overlap >= min_overlap:
            scored.append((overlap, role, text[:240]))
    if not scored:
        return []
    scored.sort(key=lambda row: row[0], reverse=True)
    seen: set[str] = set()
    out: list[str] = []
    for _, role, text in scored:
        key = text[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(f"[{role}] {text}")
        if len(out) >= max_hits:
            break
    return out


_SALIENCE_KEYWORDS = {
    "remember", "important", "promise", "deadline", "anniversary", "birthday",
    "appointment", "interview", "meeting", "exam", "wedding", "funeral",
    "kids", "spouse", "wife", "husband", "boss", "mom", "dad", "family",
    "doctor", "hospital", "medication", "allergy", "diagnosis",
    "love", "hate", "afraid", "scared", "anxious", "grateful",
    "goal", "plan", "project", "launch", "shipping",
}
_PROFILE_PREFIXES = ("profile:", "summary:", "event:", "mood:", "topic:", "trait:")


def memory_salience_score(role: str, content: str) -> float:
    """
    Heuristic salience score in [0, 5] for one memory row. Used by consolidation
    (to decide what to keep) and by future retrieval re-rankers.
    """
    text = (content or "").strip().lower()
    if not text:
        return 0.0
    score = 0.0
    if role == "note":
        score += 1.2
        for pref in _PROFILE_PREFIXES:
            if text.startswith(pref):
                score += 1.4
                break
    if role == "user":
        score += 0.4
    if role == "assistant":
        score += 0.1

    tokens = _TOKEN_RE.findall(text)
    token_set = {t.lower() for t in tokens}
    overlap = len(token_set.intersection(_SALIENCE_KEYWORDS))
    score += min(2.0, overlap * 0.6)

    # Date/time mentions are weakly salient.
    if re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", text, re.I):
        score += 0.4
    if re.search(r"\b(today|tomorrow|next week|next month)\b", text, re.I):
        score += 0.3

    # Proper-noun heuristic: capitalized words in original content.
    capitals = sum(1 for t in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", content or ""))
    if capitals >= 1:
        score += min(0.8, capitals * 0.25)

    return round(min(5.0, score), 2)


def memory_consolidate(*, force: bool = False) -> dict[str, int]:
    """
    Periodic memory cleanup. Runs at most once per ``JARVIS_MEMORY_CONSOLIDATE_HOURS``
    (default 24) unless ``force=True``.

    Steps:
    1. Trigger a normal LLM summary pass for any unsummarized backlog.
    2. Compute salience per row and delete the lowest-salience old user/assistant
       turns (keeps notes, summaries, profile facts untouched).
    """
    stamp_path = ROOT / "data" / "memory_consolidate.stamp"
    try:
        last = float(stamp_path.read_text(encoding="utf-8").strip())
    except Exception:
        last = 0.0
    now = time.time()
    try:
        hours = float(os.environ.get("JARVIS_MEMORY_CONSOLIDATE_HOURS", "24"))
    except ValueError:
        hours = 24.0
    if not force and (now - last) < max(1.0, hours) * 3600.0:
        return {"summarized": 0, "pruned": 0, "skipped": 1}

    summarized = 1 if maybe_summarize_old_turns(force=True) else 0
    pruned = _prune_low_salience(min_age_days=14, max_delete=200)

    try:
        ROOT.joinpath("data").mkdir(parents=True, exist_ok=True)
        stamp_path.write_text(str(now), encoding="utf-8")
    except Exception:
        pass
    return {"summarized": summarized, "pruned": pruned, "skipped": 0}


def _prune_low_salience(*, min_age_days: int = 14, max_delete: int = 200) -> int:
    """Delete the oldest, lowest-salience non-note rows beyond a minimum age."""
    if _use_postgres():
        return _prune_low_salience_postgres(min_age_days=min_age_days, max_delete=max_delete)
    return _prune_low_salience_sqlite(min_age_days=min_age_days, max_delete=max_delete)


def _prune_low_salience_sqlite(*, min_age_days: int, max_delete: int) -> int:
    cutoff = time.time() - max(1, min_age_days) * 86400
    with _SQL_LOCK:
        conn = sqlite3.connect(_SQLITE_PATH)
        try:
            _sqlite_ensure(conn)
            cur = conn.execute(
                """
                SELECT id, role, content FROM episodic_memory
                WHERE role IN ('user', 'assistant') AND created_at < ?
                ORDER BY id ASC
                """,
                (cutoff,),
            )
            rows = cur.fetchall()
            candidates: list[tuple[int, float]] = []
            for rid, role, content in rows:
                score = memory_salience_score(str(role), str(content))
                if score <= 0.6:
                    candidates.append((int(rid), score))
            if not candidates:
                return 0
            candidates.sort(key=lambda x: x[1])
            to_delete = [str(r[0]) for r in candidates[: max(1, max_delete)]]
            placeholders = ",".join("?" * len(to_delete))
            conn.execute(
                f"DELETE FROM episodic_memory WHERE id IN ({placeholders})",
                to_delete,
            )
            conn.commit()
            return len(to_delete)
        finally:
            conn.close()


def _prune_low_salience_postgres(*, min_age_days: int, max_delete: int) -> int:
    cutoff_seconds = max(1, min_age_days) * 86400
    with _PG_LOCK:
        conn = _pg_connect()
        try:
            _ensure_pg_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, role, content FROM jarvis_episodic_memory
                    WHERE role IN ('user', 'assistant')
                      AND created_at < NOW() - INTERVAL '{int(cutoff_seconds)} seconds'
                    ORDER BY id ASC
                    """
                )
                rows = cur.fetchall()
                candidates: list[tuple[int, float]] = []
                for rid, role, content in rows:
                    score = memory_salience_score(str(role), str(content))
                    if score <= 0.6:
                        candidates.append((int(rid), score))
                if not candidates:
                    return 0
                candidates.sort(key=lambda x: x[1])
                ids = [r[0] for r in candidates[: max(1, max_delete)]]
                with conn.cursor() as c2:
                    c2.execute(
                        "DELETE FROM jarvis_episodic_memory WHERE id = ANY(%s)",
                        (ids,),
                    )
            conn.commit()
            return len(ids)
        finally:
            conn.close()


_CONSOLIDATE_THREAD_STARTED = threading.Event()
_CONSOLIDATE_STOP = threading.Event()


def start_consolidation_daemon(*, check_seconds: int = 3600) -> None:
    """Background daemon that calls ``memory_consolidate()`` periodically."""
    if _CONSOLIDATE_THREAD_STARTED.is_set():
        return
    _CONSOLIDATE_THREAD_STARTED.set()
    _CONSOLIDATE_STOP.clear()
    interval = max(60, int(check_seconds))

    def _loop() -> None:
        while not _CONSOLIDATE_STOP.is_set():
            try:
                memory_consolidate()
            except Exception:
                pass
            _CONSOLIDATE_STOP.wait(interval)

    t = threading.Thread(target=_loop, name="jarvis-mem-consolidate", daemon=True)
    t.start()


def memory_list_summaries(*, max_rows: int = 400, max_items: int = 6) -> list[str]:
    rows = memory_recent_rows(limit=max_rows)
    out: list[str] = []
    for role, content in rows:
        if role != "note":
            continue
        c = (content or "").strip()
        if c.lower().startswith(_SUMMARY_PREFIX):
            out.append(c[len(_SUMMARY_PREFIX) :].strip())
    return out[-max_items:]


_REFLECTION_PREFIX = "reflection:"


def memory_list_reflections(*, max_rows: int = 400, max_items: int = 3) -> list[str]:
    """Return recent end-of-day reflection notes (newest last)."""
    rows = memory_recent_rows(limit=max_rows)
    out: list[str] = []
    for role, content in rows:
        if role != "note":
            continue
        c = (content or "").strip()
        if c.lower().startswith(_REFLECTION_PREFIX):
            out.append(c[len(_REFLECTION_PREFIX) :].strip())
    return out[-max_items:]


def memory_list_profile_facts(*, max_rows: int = 220, max_facts: int = 12) -> list[str]:
    """Return compact 'field: value' facts extracted from durable profile notes."""
    rows = memory_recent_rows(limit=max_rows)
    facts: dict[str, str] = {}
    for role, content in rows:
        if role != "note":
            continue
        c = (content or "").strip()
        if not c.lower().startswith("profile:"):
            continue
        m = _PROFILE_NOTE_RE.match(c)
        if not m:
            continue
        field = m.group(1).strip().lower()
        value = m.group(2).strip()
        if field and value:
            facts[field] = value

    preferred_order = ["name", "identity", "location", "work", "birthday", "preference"]
    ordered: list[str] = []
    for k in preferred_order:
        if k in facts:
            ordered.append(f"{k}: {facts[k]}")

    # Add any remaining fields.
    for k, v in facts.items():
        if k in preferred_order:
            continue
        ordered.append(f"{k}: {v}")

    return ordered[:max_facts]


def memory_list_recent_events(*, max_rows: int = 220, max_events: int = 6) -> list[str]:
    """Return durable 'event: ...' notes (best-effort)."""
    rows = memory_recent_rows(limit=max_rows)
    events: list[str] = []
    for role, content in rows:
        if role != "note":
            continue
        c = (content or "").strip()
        cl = c.lower()
        if cl.startswith("profile:"):
            continue
        if cl.startswith("event:"):
            events.append(c[len("event:") :].strip())
        else:
            # Older tool calls may store reminders without an 'event:' prefix.
            events.append(c[:140])
    return events[-max_events:]


def memory_build_user_memory_summary(*, max_profile_facts: int = 8, max_events: int = 5) -> str:
    """Speak-friendly summary for the user."""
    profile_facts = memory_list_profile_facts(max_facts=max_profile_facts)
    events = memory_list_recent_events(max_events=max_events)

    parts: list[str] = []
    if profile_facts:
        parts.append("Profile facts I have saved: " + "; ".join(profile_facts))
    else:
        parts.append("I don't have any saved profile facts yet.")

    if events:
        parts.append("Recent remembered events: " + "; ".join(events))
    else:
        parts.append("I don't have any remembered events yet.")

    return " ".join(parts)


def memory_forget_profile_facts() -> int:
    """Delete all durable profile notes (content starts with 'profile:')."""
    if _use_postgres():
        with _PG_LOCK:
            conn = _pg_connect()
            try:
                _ensure_pg_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM jarvis_episodic_memory
                        WHERE role = 'note'
                          AND substr(content, 1, 8) = 'profile:'
                        """
                    )
                    deleted = int(cur.rowcount or 0)
                conn.commit()
                return deleted
            finally:
                conn.close()

    with _SQL_LOCK:
        conn = sqlite3.connect(_SQLITE_PATH)
        try:
            _sqlite_ensure(conn)
            cur = conn.execute(
                """
                DELETE FROM episodic_memory
                WHERE role = 'note'
                  AND substr(content, 1, 8) = 'profile:'
                """
            )
            deleted = int(getattr(cur, "rowcount", None) or 0)
            conn.commit()
            return deleted
        finally:
            conn.close()


def memory_forget_notes_containing(text: str) -> int:
    """Delete durable 'note' rows whose content contains the given substring (case-insensitive)."""
    needle = (text or "").strip().lower()
    if not needle:
        return 0

    if _use_postgres():
        with _PG_LOCK:
            conn = _pg_connect()
            try:
                _ensure_pg_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM jarvis_episodic_memory
                        WHERE role = 'note'
                          AND position(lower(%s) in lower(content)) > 0
                        """,
                        (needle,),
                    )
                    deleted = int(cur.rowcount or 0)
                conn.commit()
                return deleted
            finally:
                conn.close()

    with _SQL_LOCK:
        conn = sqlite3.connect(_SQLITE_PATH)
        try:
            _sqlite_ensure(conn)
            cur = conn.execute(
                """
                DELETE FROM episodic_memory
                WHERE role = 'note'
                  AND instr(lower(content), lower(?)) > 0
                """,
                (needle,),
            )
            deleted = int(getattr(cur, "rowcount", None) or 0)
            conn.commit()
            return deleted
        finally:
            conn.close()
