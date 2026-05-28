"""Filesystem knowledge documents: paths, chunking, reindex manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT / "data"
MANIFEST_PATH = _DATA_DIR / "kb_manifest.json"
# When `JARVIS_VECTOR_BACKEND` changes without touching KB files, we still must re-ingest.
VECTOR_BACKEND_MARKER = _DATA_DIR / "kb_vector_backend.marker"


def knowledge_dir() -> Path:
    import os

    raw = os.environ.get("JARVIS_KNOWLEDGE_DIR", "").strip()
    base = Path(raw) if raw else _ROOT / "knowledge_docs"
    return base.resolve()


def chunk_max_chars() -> int:
    import os

    raw = os.environ.get("JARVIS_CHUNK_MAX_CHARS", "").strip()
    if raw.isdigit():
        return max(200, min(32000, int(raw)))
    return 900


def chunk_text(text: str, max_chars: int | None = None) -> list[str]:
    if max_chars is None:
        max_chars = chunk_max_chars()
    text = re.sub(r"\r\n", "\n", text).strip()
    if not text:
        return []
    parts = re.split(r"\n\s*\n+", text)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= max_chars:
                buf = p
            else:
                for i in range(0, len(p), max_chars):
                    chunks.append(p[i : i + max_chars])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def collect_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    # Include common text-heavy formats so the knowledge base can grow without conversions.
    for pat in (
        "**/*.txt",
        "**/*.md",
        "**/*.markdown",
        "**/*.rst",
        "**/*.log",
        "**/*.csv",
        "**/*.json",
        "**/*.yaml",
        "**/*.yml",
        "**/*.py",
    ):
        out.extend(root.glob(pat))
    return sorted({p.resolve() for p in out if p.is_file()})


def manifest_state(files: list[Path]) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in files}


def needs_reindex(current: dict[str, float]) -> bool:
    if not MANIFEST_PATH.exists():
        return True
    try:
        old = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return old != current


def write_manifest(state: dict[str, float]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(state, indent=0), encoding="utf-8")


def read_vector_backend_marker() -> str | None:
    try:
        return VECTOR_BACKEND_MARKER.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None


def write_vector_backend_marker(backend_token: str) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_BACKEND_MARKER.write_text(backend_token.strip().lower(), encoding="utf-8")


def needs_vector_resync(backend_token: str, paths_state: dict[str, float]) -> bool:
    """True if KB files changed, or embedding store backend switched (Chroma ↔ Postgres)."""
    token = backend_token.strip().lower()
    if read_vector_backend_marker() != token:
        return True
    return needs_reindex(paths_state)
