"""Inbound arguments for local.* tools (heuristic from user_text)."""

from __future__ import annotations

import re


def _quoted(text: str) -> str | None:
    m = re.search(r"\"([^\"\n]{1,4096})\"", text)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"'([^'\n]{1,4096})'", text)
    if m2:
        return m2.group(1).strip()
    return None


def _last_path_like(text: str) -> str | None:
    toks = re.findall(r"[A-Za-z0-9._\-\/\\]+(?:\.[A-Za-z0-9]{1,8})?", text)
    if not toks:
        return None
    cand = toks[-1]
    if len(cand) < 2:
        return None
    if "/" in cand or "\\" in cand or "." in cand:
        return cand
    return None


def _extract_path(user_text: str, default: str = ".") -> str:
    q = _quoted(user_text)
    if q and ("/" in q or "\\" in q or "." in q or q in (".", "..")):
        return q
    lp = _last_path_like(user_text)
    if lp:
        return lp
    return default


def _extract_app_name(user_text: str) -> str:
    q = _quoted(user_text)
    if q:
        return q
    for pat in (
        r"(?:open|launch|start|quit|close)\s+(?:the\s+)?(?:app\s+)?([A-Za-z0-9][A-Za-z0-9 .\-]{0,80})",
        r"(?:application|app)\s+([A-Za-z0-9][A-Za-z0-9 .\-]{0,80})",
    ):
        m = re.search(pat, user_text, re.I)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    toks = user_text.split()
    if toks:
        return toks[-1]
    return ""


def local_tool_inputs(tool_name: str, user_text: str) -> dict:
    if tool_name == "local.list_directory":
        return {"path": _extract_path(user_text, ".")}
    if tool_name == "local.read_file":
        return {"path": _extract_path(user_text, "README.md")}
    if tool_name == "local.write_file":
        return {
            "path": _extract_path(user_text, "notes.txt"),
            "content": user_text[:8000],
        }
    if tool_name in ("local.open_application", "local.quit_application"):
        return {"app": _extract_app_name(user_text)}
    return {}
