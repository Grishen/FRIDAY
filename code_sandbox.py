"""Sandboxed Python / shell execution with hard timeouts and output capture.

Design priorities (in order):
    1. Safety — no eval/exec in-process; runs in a subprocess, captures stdout/stderr.
    2. Predictability — hard timeout, output size cap, returns structured result.
    3. Convenience — for Python, captures the last expression value too.

Not a real sandbox (no syscall jail); the subprocess inherits user privileges.
Defaults to denying network for Python via JARVIS_SANDBOX_NETWORK=0 (best-effort
by removing common env vars); call sites that need it can pass network=True.

API:
    run_python(code, *, stdin='', timeout_s=10, network=False) -> dict
    run_shell(command, *, timeout_s=10) -> dict

Each result dict:
    {ok, exit_code, stdout, stderr, value, duration_s, truncated}
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from typing import Optional


_MAX_OUTPUT_BYTES = 64 * 1024


def _truncate(s: str) -> tuple[str, bool]:
    if not s:
        return s, False
    b = s.encode("utf-8", errors="replace")
    if len(b) <= _MAX_OUTPUT_BYTES:
        return s, False
    return b[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") + "\n...[truncated]", True


def _allow_subprocess() -> bool:
    return os.environ.get("JARVIS_SANDBOX", "1").lower() not in ("0", "false", "no", "off")


def run_python(code: str, *, stdin: str = "", timeout_s: float = 10.0,
               network: bool = False) -> dict:
    """
    Execute a Python snippet in a fresh subprocess. Captures stdout, stderr, and
    the value of the last expression (if any) under ``value``.
    """
    if not _allow_subprocess():
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "Sandbox disabled.",
                "value": None, "duration_s": 0.0, "truncated": False}
    if not (code or "").strip():
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "Empty code.",
                "value": None, "duration_s": 0.0, "truncated": False}

    # Detect a last bare expression to capture its repr.
    src = code.rstrip()
    lines = src.splitlines()
    capture_last = False
    if lines:
        last = lines[-1].strip()
        if last and not last.startswith("#") and ":" not in last and "=" not in last:
            # crude guess: if it looks like an expression, wrap it.
            capture_last = True

    if capture_last:
        body_lines = lines[:-1]
        body = "\n".join(body_lines)
        wrapped = (
            "import json, sys\n"
            "_value = None\n"
            f"{body}\n"
            f"try:\n    _value = {lines[-1]}\nexcept Exception as _exc:\n    _value = None\n"
            "if _value is not None:\n"
            "    try:\n"
            "        sys.stdout.write('\\n__JARVIS_VALUE__::' + json.dumps(_value, default=str))\n"
            "    except Exception:\n"
            "        sys.stdout.write('\\n__JARVIS_VALUE__::' + repr(_value))\n"
        )
    else:
        wrapped = code

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(wrapped)
        script_path = tf.name

    env = dict(os.environ)
    if not network:
        # Best-effort restrictions (not a true sandbox).
        for k in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            env.pop(k, None)
        env["NO_PROXY"] = "*"

    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", script_path],
            input=stdin or "",
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        try:
            os.unlink(script_path)
        except OSError:
            pass
        return {"ok": False, "exit_code": -1,
                "stdout": _truncate(exc.stdout or "")[0],
                "stderr": _truncate((exc.stderr or "") + f"\nTimed out after {timeout_s}s")[0],
                "value": None, "duration_s": time.time() - t0, "truncated": False}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass

    out = proc.stdout or ""
    value = None
    if capture_last and "__JARVIS_VALUE__::" in out:
        out, _, tail = out.rpartition("__JARVIS_VALUE__::")
        out = out.rstrip("\n")
        try:
            import json

            value = json.loads(tail)
        except Exception:
            value = tail.strip()

    stdout_t, t1 = _truncate(out)
    stderr_t, t2 = _truncate(proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": stdout_t,
        "stderr": stderr_t,
        "value": value,
        "duration_s": time.time() - t0,
        "truncated": t1 or t2,
    }


def run_shell(command: str, *, timeout_s: float = 10.0) -> dict:
    if not _allow_subprocess():
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "Sandbox disabled.",
                "value": None, "duration_s": 0.0, "truncated": False}
    if not (command or "").strip():
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "Empty command.",
                "value": None, "duration_s": 0.0, "truncated": False}

    # Refuse outright destructive patterns by default.
    deny = ("rm -rf /", ":(){:|:&};:", "mkfs.", "shutdown ", "reboot")
    if any(d in command for d in deny):
        return {"ok": False, "exit_code": -1, "stdout": "",
                "stderr": "Refused: command matches an unsafe pattern.",
                "value": None, "duration_s": 0.0, "truncated": False}

    t0 = time.time()
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=max(1.0, float(timeout_s)),
        )
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "exit_code": -1,
                "stdout": _truncate(exc.stdout or "")[0],
                "stderr": _truncate((exc.stderr or "") + f"\nTimed out after {timeout_s}s")[0],
                "value": None, "duration_s": time.time() - t0, "truncated": False}

    stdout_t, t1 = _truncate(proc.stdout or "")
    stderr_t, t2 = _truncate(proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": stdout_t,
        "stderr": stderr_t,
        "value": None,
        "duration_s": time.time() - t0,
        "truncated": t1 or t2,
    }


__all__ = ["run_python", "run_shell"]
