"""Opt-in glance mode — periodic low-rate screen awareness during work sessions."""

from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Callable, Optional

_STATE = {
    "active": False,
    "thread": None,
    "stop": threading.Event(),
    "speak_fn": None,
    "last_hash": "",
    "last_spoke_at": 0.0,
}


def _enabled() -> bool:
    return os.environ.get("JARVIS_GLANCE_MODE", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _interval_s() -> float:
    try:
        return max(60.0, float(os.environ.get("JARVIS_GLANCE_INTERVAL", "300")))
    except (TypeError, ValueError):
        return 300.0


def is_active() -> bool:
    return bool(_STATE["active"])


def start_glance_mode(speak_fn: Callable[[str], None]) -> bool:
    if not _enabled() and os.environ.get("JARVIS_GLANCE_MODE") != "force":
        # Allow voice command to force-start even if env is 0.
        pass
    t = _STATE.get("thread")
    if t and t.is_alive():
        _STATE["speak_fn"] = speak_fn
        _STATE["active"] = True
        return True
    _STATE["stop"].clear()
    _STATE["speak_fn"] = speak_fn
    _STATE["active"] = True
    _STATE["thread"] = threading.Thread(target=_loop, name="glance-mode", daemon=True)
    _STATE["thread"].start()
    return True


def stop_glance_mode() -> None:
    _STATE["active"] = False
    _STATE["stop"].set()
    t = _STATE.get("thread")
    if t and t.is_alive():
        t.join(timeout=1.0)
    _STATE["thread"] = None


def _content_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def _glance_once() -> Optional[str]:
    try:
        from awareness import active_app
        from vision import describe_screen

        app = active_app() or {}
        app_name = (app.get("name") or "").lower()
        dev_apps = {"xcode", "cursor", "visual studio code", "code", "terminal", "iterm"}
        if not any(d in app_name for d in dev_apps):
            return None

        summary = describe_screen(prompt=(
            "In one sentence: is there an error, blocker, or something the user "
            "likely needs help with? If nothing notable, reply exactly: OK"
        ))
        if not summary or summary.strip().upper() == "OK":
            return None
        if len(summary) > 220:
            summary = summary[:217] + "..."
        return summary
    except Exception:
        return None


def _loop() -> None:
    while not _STATE["stop"].is_set():
        try:
            if _STATE["active"]:
                try:
                    from ambient import is_snoozed, seconds_idle

                    if is_snoozed("glance") or seconds_idle() > 900:
                        _STATE["stop"].wait(_interval_s())
                        continue
                except Exception:
                    pass

                msg = _glance_once()
                if msg:
                    h = _content_hash(msg)
                    now = time.time()
                    min_gap = max(120.0, _interval_s() * 0.8)
                    if h != _STATE.get("last_hash") and (now - float(_STATE.get("last_spoke_at") or 0)) > min_gap:
                        _STATE["last_hash"] = h
                        _STATE["last_spoke_at"] = now
                        speak = _STATE.get("speak_fn")
                        if speak:
                            try:
                                speak(f"Glance — {msg} Want me to dig in?")
                            except Exception:
                                pass
        except Exception:
            if os.environ.get("JARVIS_GLANCE_DEBUG") == "1":
                traceback.print_exc()
        _STATE["stop"].wait(_interval_s())


__all__ = ["is_active", "start_glance_mode", "stop_glance_mode"]
