"""Cross-platform desktop helpers (notifications, future: paths, autostart).

Notifications use no extra dependencies when possible:

- **macOS:** ``osascript`` banner (Notification Center style).
- **Windows:** short PowerShell script using ``System.Windows.Forms.NotifyIcon`` balloon.
- **Linux:** ``notify-send`` if available on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile


def show_desktop_notification(
    title: str,
    body: str,
    *,
    duration_ms: int = 6000,
) -> str:
    """Show an OS-native non-blocking-ish toast/banner. Returns human-readable outcome."""
    title = (title or "Friday").strip() or "Friday"
    body = (body or "").strip() or "(no message)"
    duration_ms = max(1000, min(60000, int(duration_ms)))

    if sys.platform == "darwin":
        return _notify_macos(title, body)

    if sys.platform == "win32":
        return _notify_windows(title, body, duration_ms)

    return _notify_linux(title, body)


def _notify_macos(title: str, body: str) -> str:
    # Escape for AppleScript string literal
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    cmd = (
        f'display notification "{esc(body)}" with title "{esc(title)}"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", cmd],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "Notification displayed (macOS)."
    except Exception as exc:  # noqa: BLE001
        return f"macOS notification failed: {exc}"


def _notify_windows(title: str, body: str, duration_ms: int) -> str:
    # Avoid fragile -Command quoting: write a tiny PowerShell script.
    ps_body = (
        "Add-Type -AssemblyName System.Drawing\n"
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "$n = New-Object System.Windows.Forms.NotifyIcon\n"
        "$n.Icon = [System.Drawing.SystemIcons]::Information\n"
        "$n.Visible = $true\n"
        f"$n.ShowBalloonTip({duration_ms}, {title!r}, {body!r}, "
        "[System.Windows.Forms.ToolTipIcon]::Info)\n"
        f"Start-Sleep -Milliseconds {duration_ms + 800}\n"
        "$n.Visible = $false\n"
        "$n.Dispose()\n"
    )
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".ps1",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(ps_body)
            path = tmp.name
        kw: dict = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=min(120, duration_ms // 1000 + 25),
            **kw,
        )
        return "Notification displayed (Windows)."
    except FileNotFoundError:
        return "powershell.exe not found; cannot show Windows balloon."
    except Exception as exc:  # noqa: BLE001
        return f"Windows notification failed: {exc}"
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _notify_linux(title: str, body: str) -> str:
    exe = shutil.which("notify-send")
    if not exe:
        return "notify-send not installed; skipping Linux notification."
    try:
        subprocess.run(
            [exe, title, body],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "Notification displayed (Linux notify-send)."
    except Exception as exc:  # noqa: BLE001
        return f"Linux notification failed: {exc}"


__all__ = ["show_desktop_notification"]
