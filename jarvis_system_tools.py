"""Sandboxed PC actions for the conversational brain (open / list / read / guarded delete).

**Safety model:** Paths must resolve **inside** one of ``JARVIS_TOOL_PATH_ROOTS`` (pipe ``|``
separated absolute or user-relative paths). If unset, **only**
``data/jarvis_workspace/`` under this repo project root is writable & visible — put files there
for Friday to manipulate.

**Master switch:** ``JARVIS_FILE_TOOLS=1``

System-critical locations are **always blocked** (Windows ``Windows/System32`` etc.,
macOS ``/System`` …), even if misconfigured roots overlap.

Deletes require ``user_explicitly_confirmed_delete: true`` in the API call --- an LLM honesty
checkpoint; enforcement is actually **sandbox + blocklist**.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent


def file_tools_enabled() -> bool:
    return os.environ.get("JARVIS_FILE_TOOLS", "").strip().lower() in ("1", "true", "yes", "on")


def _default_workspace() -> Path:
    p = _REPO_ROOT / "data" / "jarvis_workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def configured_roots() -> list[Path]:
    raw = os.environ.get("JARVIS_TOOL_PATH_ROOTS", "").strip()
    if not raw:
        return [_default_workspace()]
    roots: list[Path] = []
    for part in raw.split("|"):
        s = part.strip()
        if not s:
            continue
        roots.append(Path(s).expanduser().resolve())
    return roots if roots else [_default_workspace()]


def _forbidden_roots() -> list[Path]:
    """Never operate inside these hierarchies."""
    blocked: list[Path] = []
    if sys.platform == "win32":
        for key in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)"):
            v = os.environ.get(key)
            if not v:
                continue
            try:
                blocked.append(Path(v).resolve())
            except OSError:
                pass
    elif sys.platform == "darwin":
        try:
            blocked.append(Path("/System").resolve())
            blocked.append(Path("/Library").resolve())
        except OSError:
            pass
    else:
        for extra in ("/bin", "/sbin", "/boot", "/etc", "/usr", "/lib", "/sys"):
            try:
                p = Path(extra)
                if p.exists():
                    blocked.append(p.resolve())
            except OSError:
                pass
    return blocked


def _violates_blocked_hierarchy(ap: Path) -> bool:
    try:
        rp = ap.resolve()
    except OSError:
        return True
    for bad in _forbidden_roots():
        try:
            rp.relative_to(bad)
            return True
        except ValueError:
            continue
    return False


def _inside_allowed_roots(ap: Path, roots: list[Path]) -> bool:
    try:
        rp = ap.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            rr = root.resolve()
            rp.relative_to(rr)
            return True
        except ValueError:
            continue
        except OSError:
            continue
    return False


def _guard_path(path_arg: str, roots: list[Path]) -> tuple[Path | None, str]:
    if not path_arg.strip():
        return None, "No path supplied."
    try:
        p = Path(path_arg.strip()).expanduser()
        rp = p.resolve()
    except OSError as exc:
        return None, f"Invalid path ({exc})."
    if _violates_blocked_hierarchy(rp):
        return None, "Refused: path falls under blocked system hierarchy."
    if not _inside_allowed_roots(rp, roots):
        return (
            None,
            "Refused: path escapes allowed roots. Extend JARVIS_TOOL_PATH_ROOTS (pipe-separated) "
            "or move files under data/jarvis_workspace/. "
            "See docs/FILE_TOOLS.md.",
        )
    return rp, ""



try:
    _MAX_READ_BYTES = int(os.environ.get("JARVIS_FILE_PREVIEW_BYTES", "256000"))
except ValueError:
    _MAX_READ_BYTES = 256000


def system_open_path(path_str: str) -> str:
    if not file_tools_enabled():
        return _disabled()
    roots = configured_roots()
    p, err = _guard_path(path_str, roots)
    if err or p is None:
        return err
    if not p.exists():
        return f"No such path on disk yet: {p}"
    try:
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)], check=False, capture_output=True)
        else:
            subprocess.run(["xdg-open", str(p)], check=False, capture_output=True)
        return f"Opened with default association / shell: {p}"
    except Exception as exc:  # noqa: BLE001
        return f"Open failed: {exc}"


def system_list_directory(path_str: str, max_entries: int = 120) -> str:
    if not file_tools_enabled():
        return _disabled()
    roots = configured_roots()
    p, err = _guard_path(path_str, roots)
    if err or p is None:
        return err
    if not p.is_dir():
        return f"Not a directory: {p}"
    entries: list[str] = []
    try:
        scanned = sorted(p.iterdir(), key=lambda x: x.name.lower())
    except Exception as exc:  # noqa: BLE001
        return f"List failed: {exc}"
    for child in scanned[: max(10, min(500, max_entries))]:
        mark = "/" if child.is_dir() else ""
        try:
            entries.append(child.name + mark)
        except OSError:
            continue
    if not scanned:
        return f"Directory exists but appears empty: {p}"
    more = f" (+ {len(scanned) - len(entries)} more)" if len(scanned) > len(entries) else ""
    return ", ".join(entries) + more


def system_read_text_preview(path_str: str, max_lines: int = 120) -> str:
    if not file_tools_enabled():
        return _disabled()
    roots = configured_roots()
    p, err = _guard_path(path_str, roots)
    if err or p is None:
        return err
    if not p.is_file():
        return f"Not a regular file or missing: {p}"
    lim = max(1000, min(2_000_000, _MAX_READ_BYTES))
    try:
        size = p.stat().st_size
        if size > lim:
            return f"Too large ({size} bytes): raise JARVIS_FILE_PREVIEW_BYTES or choose a smaller snippet."
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Read failed: {exc}"
    lines = text.splitlines()
    if len(lines) > max_lines:
        chunk = "\n".join(lines[:max_lines])
        return chunk + f"\n... ({len(lines) - max_lines} more lines truncated)"
    return text if text else "(empty file)"


def system_delete_paths(
    paths: list[str],
    *,
    user_explicitly_confirmed_delete: bool,
    allow_empty_directories: bool = False,
) -> str:
    if not file_tools_enabled():
        return _disabled()
    if not paths:
        return "No paths to delete supplied."
    if not user_explicitly_confirmed_delete:
        return (
            "Delete refused: only set user_explicitly_confirmed_delete=true after the user "
            "clearly asked to delete these exact paths; otherwise ask them to confirm first."
        )

    roots = configured_roots()
    results: list[str] = []

    huge_limit = int(os.environ.get("JARVIS_LARGE_FILE_DELETE_BYTES", str(1024 * 1024 * 100)))
    skip_large = os.environ.get("JARVIS_SKIP_LARGE_DELETE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    for raw in paths:
        raw = raw.strip()
        if not raw:
            continue
        p, err = _guard_path(raw, roots)
        if err or p is None:
            results.append(f"SKIP `{raw}`: {err}")
            continue
        if not p.exists():
            results.append(f"MISSING `{raw}`")
            continue
        try:
            if p.is_file():
                sz = p.stat().st_size
                if skip_large and sz > huge_limit:
                    results.append(f"SKIP (too large, {sz} bytes): {p}")
                    continue
                p.unlink()
                results.append(f"DELETED FILE {p}")
            elif p.is_dir():
                if allow_empty_directories:
                    try:
                        p.rmdir()
                        results.append(f"REMOVED EMPTY DIR {p}")
                    except OSError as exc:
                        results.append(f"DIR NOT EMPTY or fail {p}: {exc}")
                else:
                    results.append(
                        f"SKIP DIRECTORY (set allow_empty_directories for empty dirs): {p}"
                    )
            else:
                results.append(f"SKIP special node: {p}")
        except Exception as exc:  # noqa: BLE001
            results.append(f"FAILED {p}: {exc}")

    return "\n".join(results) if results else "No operations performed."


def system_launch_exe_from_path(program_name: str) -> str:
    """Runs a bare executable resolved via ``PATH`` (no interpreter args).

    Allowed names: ``^[a-zA-Z0-9._-]{1,96}$``.
    Only available when ``JARVIS_ALLOW_PATH_EXECUTABLES=1`` **and** ``JARVIS_FILE_TOOLS=1``.
    """
    name = program_name.strip()
    if not file_tools_enabled():
        return _disabled()
    flag = os.environ.get("JARVIS_ALLOW_PATH_EXECUTABLES", "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return (
            "PATH executable launch disabled — set "
            "JARVIS_ALLOW_PATH_EXECUTABLES=1 briefly when you intend this (risk: typos)."
        )
    if (
        len(name) < 1
        or len(name) > 96
        or not all(ch.isalnum() or ch in "-_." for ch in name)
    ):
        return "Executable name violates safe character whitelist."
    resolved = shutil.which(name)
    if not resolved:
        return f"No `{name}` on PATH."
    try:
        if sys.platform == "win32":
            subprocess.Popen([resolved], close_fds=True, shell=False)
        else:
            subprocess.Popen([resolved], close_fds=True, shell=False)
        return f"Started `{name}` from {resolved}"
    except Exception as exc:  # noqa: BLE001
        return f"Launch failed: {exc}"


def _disabled() -> str:
    return (
        "PC file tools are disabled. Set JARVIS_FILE_TOOLS=1 and read docs/FILE_TOOLS.md "
        "(optional JARVIS_TOOL_PATH_ROOTS)."
    )
