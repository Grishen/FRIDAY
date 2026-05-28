"""Save short voice-learned facts into the local knowledge_docs tree."""

from __future__ import annotations

import re
import time
from pathlib import Path

from knowledge.fs_index import knowledge_dir


def _slug(text: str, *, max_len: int = 48) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    if not cleaned:
        cleaned = "note"
    return cleaned[:max_len]


def save_voice_note(text: str, *, title_hint: str = "") -> str:
    """
    Persist a short user-provided fact/note as a markdown file under
    ``knowledge_docs/_voice_notes/`` so RAG can index it on next sync.
    """
    body = (text or "").strip()
    if len(body) < 8:
        return "That note is too short to save, Sir."

    root = knowledge_dir()
    out_dir = root / "_voice_notes"
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    slug = _slug(title_hint or body[:80])
    path = out_dir / f"{stamp}_{slug}.md"
    path.write_text(
        f"# Voice note ({stamp})\n\n{body}\n",
        encoding="utf-8",
        errors="replace",
    )
    try:
        from action_history import record_action

        record_action(
            kind="note",
            payload={"summary": body[:120], "file": path.name},
            undo_data={"file_path": str(path)},
        )
    except Exception:
        pass
    return f"Saved to knowledge_docs/_voice_notes/{path.name}. Say 'resync knowledge' to index it."
