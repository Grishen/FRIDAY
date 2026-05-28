"""Smart home — Spotify Web API + macOS Shortcuts / HomeKit bridge.

Spotify:
    Set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI and run
    ``python -c "import smart_home; smart_home.spotify_authenticate()"`` once.

HomeKit / scenes:
    Map spoken phrases → macOS Shortcuts (which can trigger Home automations).
    Edit ``data/jarvis_homekit_scenes.json`` or set ``JARVIS_HOMEKIT_SHORTCUTS=1``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _err(msg: str) -> dict:
    return {"ok": False, "message": msg}


# --------------------------------------------------------------------------- #
# Spotify
# --------------------------------------------------------------------------- #


def _spotify_client():
    try:
        import spotipy  # type: ignore
        from spotipy.oauth2 import SpotifyOAuth  # type: ignore
    except ImportError:
        return None, _err("spotipy not installed. `pip install spotipy`")

    cid = os.environ.get("SPOTIFY_CLIENT_ID")
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    redirect = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")
    if not (cid and secret):
        return None, _err("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in env.")
    scope = "user-modify-playback-state user-read-playback-state app-remote-control streaming"
    auth = SpotifyOAuth(client_id=cid, client_secret=secret, redirect_uri=redirect, scope=scope,
                        cache_path=os.path.expanduser("~/.cache/jarvis-spotify"))
    return spotipy.Spotify(auth_manager=auth), None


def spotify_authenticate() -> dict:
    client, err = _spotify_client()
    if err:
        return err
    try:
        me = client.current_user()
        return {"ok": True, "user": me.get("display_name") or me.get("id")}
    except Exception as exc:  # noqa: BLE001
        return _err(f"auth failed: {exc}")


def spotify_play(*, query: str = "", uri: str = "", device_name: str = "") -> dict:
    client, err = _spotify_client()
    if err:
        return err
    try:
        device_id = _resolve_device_id(client, device_name) if device_name else None
        if uri:
            client.start_playback(device_id=device_id, uris=[uri] if "track" in uri else None,
                                  context_uri=None if "track" in uri else uri)
            return {"ok": True, "playing": uri}
        if query:
            results = client.search(q=query, limit=1, type="track")
            tracks = results.get("tracks", {}).get("items", [])
            if not tracks:
                return _err(f"No tracks for '{query}'")
            t = tracks[0]
            client.start_playback(device_id=device_id, uris=[t["uri"]])
            return {"ok": True, "playing": f"{t['name']} — {t['artists'][0]['name']}"}
        client.start_playback(device_id=device_id)
        return {"ok": True, "playing": "resumed"}
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


def spotify_pause() -> dict:
    client, err = _spotify_client()
    if err:
        return err
    try:
        client.pause_playback()
        return {"ok": True}
    except Exception as exc:
        return _err(str(exc))


def spotify_now_playing() -> dict:
    client, err = _spotify_client()
    if err:
        return err
    try:
        cur = client.current_playback()
        if not cur or not cur.get("item"):
            return {"ok": True, "playing": None}
        item = cur["item"]
        return {"ok": True,
                "playing": f"{item['name']} — {item['artists'][0]['name']}",
                "is_playing": cur.get("is_playing"),
                "device": (cur.get("device") or {}).get("name")}
    except Exception as exc:
        return _err(str(exc))


def spotify_devices() -> dict:
    client, err = _spotify_client()
    if err:
        return err
    try:
        ds = client.devices().get("devices", [])
        return {"ok": True, "devices": [{"name": d["name"], "type": d["type"],
                                          "id": d["id"], "is_active": d.get("is_active")}
                                         for d in ds]}
    except Exception as exc:
        return _err(str(exc))


def spotify_transfer(device_name: str) -> dict:
    client, err = _spotify_client()
    if err:
        return err
    try:
        device_id = _resolve_device_id(client, device_name)
        if not device_id:
            return _err(f"No device matching '{device_name}'")
        client.transfer_playback(device_id=device_id, force_play=True)
        return {"ok": True, "transferred_to": device_name}
    except Exception as exc:
        return _err(str(exc))


def _resolve_device_id(client, name: str) -> Optional[str]:
    needle = (name or "").lower()
    for d in client.devices().get("devices", []):
        if d["name"].lower() == needle or needle in d["name"].lower():
            return d["id"]
    return None


# --------------------------------------------------------------------------- #
# HomeKit via macOS Shortcuts
# --------------------------------------------------------------------------- #


def _data_dir() -> Path:
    base = Path(os.environ.get("JARVIS_DATA_DIR", "data"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _scene_map_path() -> Path:
    return _data_dir() / "jarvis_homekit_scenes.json"


def _default_scene_map() -> dict[str, str]:
    return {
        "good night": "Good Night",
        "goodnight": "Good Night",
        "movie mode": "Movie Mode",
        "movie time": "Movie Mode",
        "i'm home": "I'm Home",
        "im home": "I'm Home",
        "leaving home": "Leaving Home",
        "leave home": "Leaving Home",
        "focus mode": "Focus Mode",
        "work mode": "Focus Mode",
    }


def _load_scene_map() -> dict[str, str]:
    path = _scene_map_path()
    merged = _default_scene_map()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(k, str) and isinstance(v, str):
                        merged[k.strip().lower()] = v.strip()
        except Exception:
            pass
    return merged


def list_homekit_scenes() -> list[str]:
    """Unique shortcut names from the scene map."""
    return sorted(set(_load_scene_map().values()))


def _homekit_enabled() -> bool:
    return os.environ.get("JARVIS_HOMEKIT_SHORTCUTS", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _run_shortcut(name: str, *, input_text: str = "") -> dict:
    if sys.platform != "darwin":
        return _err("Shortcuts integration is macOS only.")
    if not _homekit_enabled():
        return _err("HomeKit shortcuts disabled. Set JARVIS_HOMEKIT_SHORTCUTS=1.")
    if not shutil.which("shortcuts"):
        return _err("shortcuts CLI not found (macOS 12+).")
    cmd = ["shortcuts", "run", name]
    if input_text:
        cmd.extend(["--input-text", input_text])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "shortcut failed").strip()
        return _err(err[:300])
    out = (res.stdout or "").strip()
    return {"ok": True, "message": out or f"Ran shortcut '{name}'.", "output": out}


def _resolve_scene(name: str) -> str:
    key = (name or "").strip().lower()
    mapping = _load_scene_map()
    if key in mapping:
        return mapping[key]
    # Allow direct shortcut name passthrough.
    return name.strip()


def homekit_set_scene(name: str) -> dict:
    shortcut = _resolve_scene(name)
    if not shortcut:
        return _err("Scene name required.")
    result = _run_shortcut(shortcut)
    if result.get("ok"):
        result["scene"] = shortcut
        result["message"] = f"Activated scene {shortcut}."
    return result


def homekit_set_light(name: str, *, on: bool = True, brightness: Optional[int] = None) -> dict:
    """
    Run a light shortcut. Default naming: ``Jarvis Light On <name>`` etc.
    Override via ``data/jarvis_homekit_scenes.json`` keys like ``light:desk:on``.
    """
    key_base = (name or "").strip().lower()
    if not key_base:
        return _err("Light name required.")
    mapping = _load_scene_map()
    if brightness is not None:
        pct = max(1, min(100, int(brightness)))
        key = f"light:{key_base}:dim:{pct}"
        if key not in mapping:
            key = f"light:{key_base}:dim"
    elif on:
        key = f"light:{key_base}:on"
    else:
        key = f"light:{key_base}:off"

    if key in mapping:
        return _run_shortcut(mapping[key])

    # Generic fallback shortcut names — user creates these once in Shortcuts.app.
    if brightness is not None:
        pct = max(1, min(100, int(brightness)))
        shortcut = os.environ.get("JARVIS_HOMEKIT_DIM_SHORTCUT", "Jarvis Dim Light")
        return _run_shortcut(shortcut, input_text=f"{name}|{pct}")
    if on:
        shortcut = os.environ.get("JARVIS_HOMEKIT_ON_SHORTCUT", "Jarvis Light On")
    else:
        shortcut = os.environ.get("JARVIS_HOMEKIT_OFF_SHORTCUT", "Jarvis Light Off")
    return _run_shortcut(shortcut, input_text=name)


def save_scene_alias(spoken: str, shortcut_name: str) -> str:
    """Persist a new spoken phrase → Shortcuts name mapping."""
    key = (spoken or "").strip().lower()
    val = (shortcut_name or "").strip()
    if not key or not val:
        return "Need both a spoken phrase and a shortcut name."
    path = _scene_map_path()
    data = _load_scene_map()
    data[key] = val
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return f"Mapped '{spoken}' → shortcut '{val}'."


__all__ = [
    "homekit_set_light",
    "homekit_set_scene",
    "list_homekit_scenes",
    "save_scene_alias",
    "spotify_authenticate",
    "spotify_devices",
    "spotify_now_playing",
    "spotify_pause",
    "spotify_play",
    "spotify_transfer",
]
