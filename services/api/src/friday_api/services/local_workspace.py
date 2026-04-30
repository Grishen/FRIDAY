"""Resolve workspace paths safely (no escapes above configured root)."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


def normalize_relative(rel: str) -> str:
    """Join-path helper for tests — canonical slash form without traversing filesystem."""

    s = rel.strip().replace("\\", "/")
    if s.startswith("/") or re.match(r"^[a-zA-Z]:", s):
        return s
    parts: list[str] = []
    for part in PurePosixPath(s).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts) if parts else "."


def strip_leading_absolute_markers(raw: str) -> str:
    """Treat leading slashes as relative to the workspace root."""

    s = raw.strip().replace("\\", "/")
    while s.startswith("/"):
        s = s[1:]
    return s or "."


def safe_join_workspace(root: Path, relative: str) -> Path:
    """Return resolved path constrained under ``root`` (no absolute inputs, rejects breakout)."""

    root_r = Path(root).expanduser().resolve()
    raw = relative.strip().replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
        raise ValueError("absolute_path_not_allowed")

    cur = root_r
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if cur == root_r:
                raise ValueError("path_escape")
            cur = cur.parent
            continue
        cur = (cur / part).resolve()
        try:
            cur.relative_to(root_r)
        except ValueError as e:
            raise ValueError("path_escape") from e
    return cur
