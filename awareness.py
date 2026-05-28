"""Situational awareness probes — what app you're in, focus mode, weather, location.

All functions are best-effort: each returns ``None`` (or an empty struct) when
the platform doesn't support it or a dependency is missing. Nothing here ever
raises out to a caller; this module is meant to be polled by the ambient
daemon and the brain at will.

Public surface:
    active_app()           -> {'name','window_title','bundle_id'}  | None
    focus_mode()           -> str (e.g. 'Do Not Disturb', 'Work') | None
    screen_locked()        -> bool | None
    is_on_battery()        -> bool | None      (alias of platform_services.is_on_battery)
    weather_summary()      -> str | None       (uses briefing.fetch_weather_summary if available)
    public_ip_geo()        -> {'city','region','country','lat','lon'} | None
    network_ssid()         -> str | None
    describe_environment() -> str (one-line voice-friendly summary)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Optional

_CACHE: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl_s: float, fn):
    now = time.time()
    if key in _CACHE:
        ts, val = _CACHE[key]
        if (now - ts) < ttl_s:
            return val
    try:
        val = fn()
    except Exception:
        val = None
    _CACHE[key] = (now, val)
    return val


def _run(cmd: list[str], timeout: float = 4.0) -> tuple[int, str, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, (res.stdout or ""), (res.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


# --------------------------------------------------------------------------- #
# Active app / window
# --------------------------------------------------------------------------- #


_OSA_ACTIVE_APP = '''
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set bundleID to bundle identifier of frontApp
    try
        set winName to name of front window of frontApp
    on error
        set winName to ""
    end try
end tell
return appName & "\\u0001" & bundleID & "\\u0001" & winName
'''


def _active_app_macos() -> Optional[dict]:
    if not shutil.which("osascript"):
        return None
    rc, out, _ = _run(["osascript", "-e", _OSA_ACTIVE_APP])
    if rc != 0 or not out:
        return None
    parts = out.strip().split("\u0001")
    if len(parts) < 2:
        return None
    return {
        "name": parts[0].strip(),
        "bundle_id": parts[1].strip(),
        "window_title": parts[2].strip() if len(parts) > 2 else "",
    }


def _active_app_windows() -> Optional[dict]:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            import psutil  # type: ignore

            proc = psutil.Process(int(pid.value))
            name = proc.name()
        except Exception:
            name = ""
        return {"name": name, "bundle_id": "", "window_title": buf.value or ""}
    except Exception:
        return None


def _active_app_linux() -> Optional[dict]:
    if shutil.which("xdotool"):
        rc, win_id, _ = _run(["xdotool", "getactivewindow"])
        if rc == 0 and win_id.strip():
            wid = win_id.strip()
            _, title, _ = _run(["xdotool", "getwindowname", wid])
            _, pid_out, _ = _run(["xdotool", "getwindowpid", wid])
            name = ""
            try:
                import psutil  # type: ignore

                proc = psutil.Process(int(pid_out.strip()))
                name = proc.name()
            except Exception:
                pass
            return {"name": name, "bundle_id": "", "window_title": title.strip()}
    return None


def active_app() -> Optional[dict]:
    def _fetch():
        if sys.platform == "darwin":
            return _active_app_macos()
        if sys.platform == "win32":
            return _active_app_windows()
        return _active_app_linux()

    return _cached("active_app", 3.0, _fetch)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Focus mode
# --------------------------------------------------------------------------- #


def _focus_mode_macos() -> Optional[str]:
    """Read macOS Focus mode from the assertions database via `defaults`."""
    if sys.platform != "darwin":
        return None
    path = os.path.expanduser(
        "~/Library/DoNotDisturb/DB/Assertions.json"
    )
    if not os.path.isfile(path):
        path = os.path.expanduser(
            "~/Library/DoNotDisturb/DB/ModeConfigurations.json"
        )
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    try:
        records = data.get("data", [{}])[0].get("storeAssertionRecords", [])
        for rec in records:
            details = rec.get("assertionDetails", {})
            mode = (details.get("assertionDetailsModeIdentifier")
                    or details.get("assertionDetailsModeName"))
            if mode:
                if "work" in mode.lower():
                    return "Work"
                if "sleep" in mode.lower():
                    return "Sleep"
                if "personal" in mode.lower():
                    return "Personal"
                if "dnd" in mode.lower() or "donotdisturb" in mode.lower():
                    return "Do Not Disturb"
                return str(mode)
    except Exception:
        pass
    return None


def focus_mode() -> Optional[str]:
    return _cached("focus_mode", 30.0, _focus_mode_macos)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Screen lock
# --------------------------------------------------------------------------- #


def _screen_locked_macos() -> Optional[bool]:
    rc, out, _ = _run(["ioreg", "-n", "Root", "-d1", "-a"])
    if rc != 0 or not out:
        return None
    return "CGSSessionScreenIsLocked" in out and '"CGSSessionScreenIsLocked" = true' in out


def screen_locked() -> Optional[bool]:
    if sys.platform != "darwin":
        return None
    return _cached("screen_locked", 5.0, _screen_locked_macos)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Power
# --------------------------------------------------------------------------- #


def is_on_battery() -> Optional[bool]:
    try:
        import platform_services  # type: ignore

        return platform_services.is_on_battery()
    except Exception:
        return None


def battery_percent() -> Optional[float]:
    try:
        import platform_services  # type: ignore

        return platform_services.battery_percent()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #


def weather_summary() -> Optional[str]:
    def _fetch():
        try:
            from briefing import fetch_weather_summary

            return fetch_weather_summary()
        except Exception:
            return None

    return _cached("weather", 900.0, _fetch)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Location & network
# --------------------------------------------------------------------------- #


def public_ip_geo() -> Optional[dict]:
    def _fetch():
        try:
            import requests
        except ImportError:
            return None
        try:
            r = requests.get("https://ipinfo.io/json", timeout=5)
            r.raise_for_status()
            data = r.json()
            loc = (data.get("loc") or "").split(",")
            return {
                "city": data.get("city"),
                "region": data.get("region"),
                "country": data.get("country"),
                "lat": float(loc[0]) if len(loc) == 2 else None,
                "lon": float(loc[1]) if len(loc) == 2 else None,
            }
        except Exception:
            return None

    return _cached("geo", 3600.0, _fetch)  # type: ignore[return-value]


def network_ssid() -> Optional[str]:
    def _fetch():
        if sys.platform == "darwin":
            # macOS 14+ removed /usr/sbin/airport CLI; use `networksetup` fallback.
            for cmd in (
                ["networksetup", "-getairportnetwork", "en0"],
                ["networksetup", "-getairportnetwork", "en1"],
            ):
                rc, out, _ = _run(cmd)
                if rc == 0 and "Current Wi-Fi Network:" in out:
                    return out.split(":", 1)[1].strip()
            return None
        if sys.platform.startswith("linux") and shutil.which("iwgetid"):
            rc, out, _ = _run(["iwgetid", "-r"])
            if rc == 0 and out.strip():
                return out.strip()
            return None
        if sys.platform == "win32":
            rc, out, _ = _run(["netsh", "wlan", "show", "interfaces"])
            if rc == 0:
                m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.MULTILINE)
                if m:
                    return m.group(1).strip()
            return None
        return None

    return _cached("ssid", 60.0, _fetch)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Composite summary
# --------------------------------------------------------------------------- #


def describe_environment() -> str:
    bits: list[str] = []
    app = active_app()
    if app and app.get("name"):
        win = app.get("window_title") or ""
        if win:
            bits.append(f'in {app["name"]} ("{win[:60]}")')
        else:
            bits.append(f"in {app['name']}")
    fm = focus_mode()
    if fm:
        bits.append(f"Focus: {fm}")
    pct = battery_percent()
    on_batt = is_on_battery()
    if pct is not None:
        bits.append(f"battery {int(pct)}%{'' if not on_batt else ' (unplugged)'}")
    geo = public_ip_geo()
    if geo and (geo.get("city") or geo.get("region")):
        loc = ", ".join(x for x in (geo.get("city"), geo.get("region")) if x)
        bits.append(f"location: {loc}")
    wx = weather_summary()
    if wx:
        bits.append(f"weather: {wx}")
    if not bits:
        return "I don't have any environment signals at the moment, Sir."
    return "; ".join(bits) + "."


__all__ = [
    "active_app",
    "battery_percent",
    "describe_environment",
    "focus_mode",
    "is_on_battery",
    "network_ssid",
    "public_ip_geo",
    "screen_locked",
    "weather_summary",
]
