"""Environment-aware proactive suggestions.

Combines :mod:`awareness` signals (front app, window title, battery, focus)
with optional screen triage to offer helpful, non-intrusive nudges via the
ambient daemon.
"""

from __future__ import annotations

import os
import re
from typing import Optional

_ERROR_TITLE_RE = re.compile(
    r"\b(error|failed|failure|exception|warning|build failed|debug|traceback|"
    r"cannot find|not found|syntax error)\b",
    re.I,
)
_DEV_APPS = {
    "xcode", "visual studio code", "code", "cursor", "terminal", "iterm",
    "pycharm", "intellij", "webstorm", "sublime text", "vim", "neovim",
}
_BROWSER_APPS = {"safari", "google chrome", "firefox", "arc", "brave browser", "microsoft edge"}


def _enabled() -> bool:
    return os.environ.get("JARVIS_ENV_COACH", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _as_question(msg: str) -> str:
    m = (msg or "").strip().rstrip(".")
    if not m:
        return m
    if m.endswith("?"):
        return m
    starters = ("want me to", "should i", "would you like me to", "shall i")
    low = m.lower()
    if any(low.startswith(s) for s in starters):
        return m + ("?" if not m.endswith("?") else "")
    return f"Want me to {m[0].lower()}{m[1:]}" if len(m) > 1 else f"Want me to {m}?"


def environment_suggestion(*, fired_key_prefix: str = "envcoach") -> Optional[str]:
    """
    Return a single proactive suggestion string, or None.

    ``fired_key_prefix`` is used with ambient's de-dupe keys.
    """
    if not _enabled():
        return None

    try:
        from ambient import has_fired, mark_fired, seconds_idle, is_dnd
        from awareness import active_app, battery_percent, focus_mode, is_on_battery
    except Exception:
        return None

    if is_dnd():
        return None
    if seconds_idle() > 120:
        return None  # user stepped away

    fm = focus_mode()
    if fm and "do not disturb" in fm.lower():
        return None

    app = active_app() or {}
    app_name = (app.get("name") or "").strip()
    title = (app.get("window_title") or "").strip()
    app_low = app_name.lower()

    # Dev tool + error-ish window title → offer screen help.
    if app_low in _DEV_APPS or any(d in app_low for d in _DEV_APPS):
        if title and _ERROR_TITLE_RE.search(title):
            key = f"{fired_key_prefix}:dev_error:{app_low}:{title[:40]}"
            if has_fired(key):
                return None
            mark_fired(key)
            return _as_question(f"look at your screen and help with the {app_name} error")

    # Browser on a doc-ish title.
    if app_low in _BROWSER_APPS and title:
        if len(title) > 12 and not has_fired(f"{fired_key_prefix}:browser:{title[:30]}"):
            mark_fired(f"{fired_key_prefix}:browser:{title[:30]}")
            short = title[:50] + ("…" if len(title) > 50 else "")
            return _as_question(f"summarize what's on this page — {short}")

    # Low battery while unplugged.
    pct = battery_percent()
    on_batt = is_on_battery()
    if pct is not None and on_batt and pct <= 15:
        key = f"{fired_key_prefix}:battery_critical"
        if not has_fired(key):
            mark_fired(key)
            return f"Battery is at {int(pct)} percent and you're unplugged — want me to note anything before you lose power?"

    return None


__all__ = ["environment_suggestion"]
