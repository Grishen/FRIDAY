"""Governed host automation — filesystem inside FRIDAY_LOCAL_WORKSPACE + allowlisted apps."""

from __future__ import annotations

import asyncio
import platform
from pathlib import Path
from uuid import UUID

from friday_api.config import get_settings
from friday_api.services.local_workspace import safe_join_workspace, strip_leading_absolute_markers


def _workspace_or_error() -> tuple[Path | None, dict | None]:
    s = get_settings()
    raw = s.friday_local_workspace.strip()
    if not raw:
        return None, {"ok": False, "error": "local_tools_disabled_set_FRIDAY_LOCAL_WORKSPACE"}
    root = Path(raw).expanduser()
    if not root.is_dir():
        return None, {"ok": False, "error": "workspace_not_a_directory"}
    return root.resolve(), None


def _allowlist() -> list[str]:
    raw = get_settings().friday_open_app_allowlist.strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _match_app(requested: str, allowed: list[str]) -> str | None:
    r = requested.strip().lower()
    if not r:
        return None
    for a in allowed:
        al = a.lower()
        if al == r or r in al or al in r:
            return a
    return None


async def tool_local_list_directory(path: str, user_id: UUID, **_kw: object) -> dict:
    _ = user_id
    root, err = _workspace_or_error()
    if err:
        return err
    assert root is not None
    try:
        target = safe_join_workspace(root, strip_leading_absolute_markers(path))
    except ValueError:
        return {"ok": False, "error": "path_escape"}
    if not target.exists():
        return {"ok": False, "error": "not_found"}
    if not target.is_dir():
        return {"ok": False, "error": "not_a_directory"}
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: p.name.lower())[:500]:
        entries.append({"name": child.name, "is_dir": child.is_dir()})
    return {"ok": True, "path": str(target.relative_to(root)), "entries": entries}


async def tool_local_read_file(path: str, user_id: UUID, **_kw: object) -> dict:
    _ = user_id
    root, err = _workspace_or_error()
    if err:
        return err
    assert root is not None
    try:
        target = safe_join_workspace(root, strip_leading_absolute_markers(path))
    except ValueError:
        return {"ok": False, "error": "path_escape"}
    if not target.is_file():
        return {"ok": False, "error": "not_found_or_not_file"}
    max_bytes = 512_000
    data = target.read_bytes()
    if len(data) > max_bytes:
        return {"ok": False, "error": "file_too_large", "limit_bytes": max_bytes}
    text = data.decode("utf-8", errors="replace")
    return {"ok": True, "path": str(target.relative_to(root)), "content": text}


async def tool_local_write_file(path: str, content: str, user_id: UUID, **_kw: object) -> dict:
    """Creates/overwrites UTF-8 text only; runs after approval (often via Celery worker)."""

    _ = user_id
    root, err = _workspace_or_error()
    if err:
        return err
    assert root is not None
    try:
        target = safe_join_workspace(root, strip_leading_absolute_markers(path))
    except ValueError:
        return {"ok": False, "error": "path_escape"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target.relative_to(root)), "bytes_written": len(content.encode("utf-8"))}


async def _run_proc(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return proc.returncode, out_b.decode("utf-8", errors="replace"), err_b.decode("utf-8", errors="replace")


async def tool_local_open_application(app: str, user_id: UUID, **_kw: object) -> dict:
    _ = user_id
    allowed = _allowlist()
    canon = _match_app(app, allowed)
    if not canon:
        return {"ok": False, "error": "app_not_allowlisted"}
    sys = platform.system()
    if sys == "Darwin":
        code, out, err = await _run_proc(["open", "-a", canon])
    elif sys == "Windows":
        code, out, err = await _run_proc(["cmd.exe", "/c", "start", "", canon])
    else:
        code, out, err = await _run_proc(["xdg-open", canon])
    ok = code == 0
    payload: dict = {"ok": ok, "app": canon, "platform": sys}
    if out.strip():
        payload["stdout"] = out[:2000]
    if err.strip():
        payload["stderr"] = err[:2000]
    return payload


async def tool_local_quit_application(app: str, user_id: UUID, **_kw: object) -> dict:
    _ = user_id
    allowed = _allowlist()
    canon = _match_app(app, allowed)
    if not canon:
        return {"ok": False, "error": "app_not_allowlisted"}
    sys = platform.system()
    if sys != "Darwin":
        return {"ok": False, "error": "quit_supported_on_macos_only"}
    script = f'tell application "{canon.replace(chr(34), "")}" to quit'
    code, out, err = await _run_proc(["osascript", "-e", script])
    ok = code == 0
    payload: dict = {"ok": ok, "app": canon, "platform": sys}
    if err.strip():
        payload["stderr"] = err[:2000]
    return payload
