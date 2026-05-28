"""Multi-user identity for memory scoping.

A lightweight identity layer so the same Jarvis install can keep separate
memories per speaker. The active user is persisted to a small file so it
survives restarts; voice / brain code reads the active user lazily.

This is intentionally manual switching for now (e.g. *"switch user to dig"*,
*"I'm alice"*). A future voiceprint module can call ``set_active_user``
automatically when it identifies the speaker.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
_DATA = ROOT / "data"
_ACTIVE_FILE = _DATA / "jarvis_active_user.json"
_USERS_FILE = _DATA / "jarvis_users.json"
_LOCK = threading.Lock()

DEFAULT_USER = "default"
_VALID_USER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")


def _load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _save_json(path: Path, data) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_user_id(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    return s or DEFAULT_USER


def is_valid_user_id(raw: str) -> bool:
    return bool(_VALID_USER_RE.match((raw or "").strip().lower()))


def active_user() -> str:
    with _LOCK:
        data = _load_json(_ACTIVE_FILE, {})
    uid = str((data or {}).get("user_id") or DEFAULT_USER)
    return uid if is_valid_user_id(uid) else DEFAULT_USER


def ensure_user(user_id: str, *, display_name: Optional[str] = None) -> str:
    uid = _normalize_user_id(user_id)
    with _LOCK:
        users = _load_json(_USERS_FILE, {})
        if not isinstance(users, dict):
            users = {}
        entry = users.get(uid) or {}
        if display_name:
            entry["display_name"] = display_name.strip()
        entry.setdefault("created_at", time.time())
        entry["last_seen"] = time.time()
        users[uid] = entry
        _save_json(_USERS_FILE, users)
    return uid


def set_active_user(user_id: str, *, display_name: Optional[str] = None) -> str:
    uid = ensure_user(user_id, display_name=display_name)
    with _LOCK:
        _save_json(_ACTIVE_FILE, {"user_id": uid, "set_at": time.time()})
    return uid


def list_users() -> list[dict[str, str]]:
    with _LOCK:
        users = _load_json(_USERS_FILE, {})
    if not isinstance(users, dict):
        return []
    out: list[dict[str, str]] = []
    for uid, entry in users.items():
        out.append(
            {
                "user_id": str(uid),
                "display_name": str((entry or {}).get("display_name") or uid),
                "last_seen": str((entry or {}).get("last_seen") or ""),
            }
        )
    out.sort(key=lambda r: r["user_id"])
    return out


def describe_active_user() -> str:
    uid = active_user()
    users = _load_json(_USERS_FILE, {})
    entry = (users or {}).get(uid) or {}
    name = entry.get("display_name") or uid
    return f"Active user: {name} (id: {uid})."


_SWITCH_PATTERNS = [
    re.compile(r"^switch (?:to )?user (?:to )?([a-z0-9 ._-]{1,40})$", re.I),
    re.compile(r"^set (?:active )?user (?:to )?([a-z0-9 ._-]{1,40})$", re.I),
    re.compile(r"^i(?:'m| am) ([a-z0-9 ._-]{1,40})$", re.I),
    re.compile(r"^this is ([a-z0-9 ._-]{1,40})$", re.I),
    re.compile(r"^who am i$", re.I),
    re.compile(r"^list users$", re.I),
]


def parse_user_command(text: str) -> tuple[str, str]:
    """
    Return ``(intent, value)``. ``intent`` is one of:

    - ``switch`` (value = requested user id / display name)
    - ``who``   (value = '')
    - ``list``  (value = '')
    - ``''``    (no match)
    """
    raw = (text or "").strip()
    if not raw:
        return "", ""

    for pat in _SWITCH_PATTERNS[:4]:
        m = pat.match(raw)
        if m:
            return "switch", m.group(1).strip()

    if _SWITCH_PATTERNS[4].match(raw):
        return "who", ""
    if _SWITCH_PATTERNS[5].match(raw):
        return "list", ""
    return "", ""


__all__ = [
    "DEFAULT_USER",
    "active_user",
    "describe_active_user",
    "ensure_user",
    "is_valid_user_id",
    "list_users",
    "parse_user_command",
    "set_active_user",
]
