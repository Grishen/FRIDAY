"""macOS automation via AppleScript: Music/Spotify control, Messages, Notes, Mail,
brightness, volume.

Every function is a no-op on non-macOS (returns an error dict) so the brain
can fail soft. Each function returns ``{ok, message, output}``.

Useful spoken commands powered by these:
    "play music"
    "pause music"
    "next song"
    "volume up" / "volume down" / "set volume to 60"
    "send a message to Alex saying hi"
    "create a note titled X with body Y"
    "open finder at ~/Downloads"
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Optional


def _macos() -> bool:
    return sys.platform == "darwin"


def _osascript(script: str, *, timeout: float = 8.0) -> dict:
    if not _macos():
        return {"ok": False, "message": "AppleScript only runs on macOS.", "output": ""}
    if not shutil.which("osascript"):
        return {"ok": False, "message": "osascript not found.", "output": ""}
    try:
        res = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc), "output": ""}
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    return {"ok": res.returncode == 0, "message": err or "ok", "output": out}


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


# --------------------------------------------------------------------------- #
# Music control
# --------------------------------------------------------------------------- #


def music_app() -> str:
    """Return 'Spotify' if installed, else 'Music'."""
    import os

    if os.path.isdir("/Applications/Spotify.app") or os.path.isdir("/System/Applications/Spotify.app"):
        return "Spotify"
    return "Music"


def music_play() -> dict:
    app = music_app()
    return _osascript(f'tell application "{app}" to play')


def music_pause() -> dict:
    app = music_app()
    return _osascript(f'tell application "{app}" to pause')


def music_next() -> dict:
    app = music_app()
    return _osascript(f'tell application "{app}" to next track')


def music_previous() -> dict:
    app = music_app()
    return _osascript(f'tell application "{app}" to previous track')


def music_now_playing() -> dict:
    app = music_app()
    return _osascript(
        f'tell application "{app}" to return name of current track & " — " & artist of current track'
    )


def music_search_and_play(query: str) -> dict:
    """Search & play on Spotify (best-effort) or play the next match in Music."""
    if not query.strip():
        return {"ok": False, "message": "empty query", "output": ""}
    app = music_app()
    q = _esc(query)
    if app == "Spotify":
        # Use Spotify URI search via spotify:search:
        script = (
            f'tell application "Spotify"\n'
            f'  set theURI to "spotify:search:{q}"\n'
            f'  open location theURI\n'
            f'  delay 2\n'
            f'  play\n'
            f'end tell'
        )
    else:
        script = (
            f'tell application "Music"\n'
            f'  set theResults to (every track of library playlist 1 whose name contains "{q}")\n'
            f'  if (count of theResults) > 0 then\n'
            f'    play item 1 of theResults\n'
            f'  end if\n'
            f'end tell'
        )
    return _osascript(script, timeout=12.0)


# --------------------------------------------------------------------------- #
# System volume / brightness
# --------------------------------------------------------------------------- #


def set_system_volume(level: int) -> dict:
    level = max(0, min(100, int(level)))
    return _osascript(f"set volume output volume {level}")


def system_volume_up(step: int = 10) -> dict:
    return _osascript(
        f"set volume output volume (output volume of (get volume settings)) + {int(step)}"
    )


def system_volume_down(step: int = 10) -> dict:
    return _osascript(
        f"set volume output volume (output volume of (get volume settings)) - {int(step)}"
    )


def mute_system(mute: bool = True) -> dict:
    val = "true" if mute else "false"
    return _osascript(f"set volume with output muted {val}" if mute
                      else "set volume without output muted")


# --------------------------------------------------------------------------- #
# Messages / Notes / Mail / Finder
# --------------------------------------------------------------------------- #


def send_imessage(recipient: str, text: str) -> dict:
    """Send an iMessage. ``recipient`` can be a phone, email, or 'first name' if in Contacts."""
    if not recipient.strip() or not text.strip():
        return {"ok": False, "message": "recipient and text required", "output": ""}
    r = _esc(recipient.strip())
    t = _esc(text.strip())
    script = (
        f'tell application "Messages"\n'
        f'  set theBuddy to first buddy of service 1 whose name contains "{r}"\n'
        f'  send "{t}" to theBuddy\n'
        f'end tell'
    )
    res = _osascript(script, timeout=10.0)
    if res["ok"]:
        return res
    # Fallback: try targeting the recipient as a literal handle (phone/email).
    fallback = (
        f'tell application "Messages"\n'
        f'  set targetService to first service whose service type = iMessage\n'
        f'  set targetBuddy to buddy "{r}" of targetService\n'
        f'  send "{t}" to targetBuddy\n'
        f'end tell'
    )
    return _osascript(fallback, timeout=10.0)


def create_note(title: str, body: str = "") -> dict:
    t = _esc(title)
    b = _esc(body)
    script = (
        f'tell application "Notes"\n'
        f'  tell account "iCloud"\n'
        f'    make new note at folder "Notes" with properties '
        f'{{name:"{t}", body:"{t}<br><br>{b}"}}\n'
        f'  end tell\n'
        f'end tell'
    )
    return _osascript(script, timeout=10.0)


def open_finder_at(path: str) -> dict:
    import os

    expanded = os.path.expanduser(path or "~")
    return _osascript(f'tell application "Finder" to open POSIX file "{_esc(expanded)}"')


def lock_screen() -> dict:
    """Lock the screen (uses pmset on macOS)."""
    if not _macos():
        return {"ok": False, "message": "macOS only", "output": ""}
    try:
        subprocess.run(["pmset", "displaysleepnow"], check=False, timeout=5)
        return {"ok": True, "message": "Screen locked.", "output": ""}
    except Exception as exc:
        return {"ok": False, "message": str(exc), "output": ""}


__all__ = [
    "create_note",
    "lock_screen",
    "mute_system",
    "music_app",
    "music_next",
    "music_now_playing",
    "music_pause",
    "music_play",
    "music_previous",
    "music_search_and_play",
    "open_finder_at",
    "send_imessage",
    "set_system_volume",
    "system_volume_down",
    "system_volume_up",
]
