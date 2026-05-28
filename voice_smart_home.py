"""Fast-path voice parsing for Spotify + HomeKit/Shortcuts (no brain round-trip)."""

from __future__ import annotations

import json
import re
from typing import Optional


def _speakable_result(payload: dict) -> str:
    if payload.get("ok"):
        for key in ("playing", "message", "output", "transferred_to"):
            val = payload.get(key)
            if val:
                return str(val)
        return "Done."
    return str(payload.get("message") or payload.get("error") or "That didn't work.")


def try_handle_smart_home(query: str) -> Optional[str]:
    """
    If ``query`` matches a music/home pattern, run it and return a speakable reply.
    """
    q = (query or "").strip().lower()
    if not q:
        return None

    # --- Spotify -----------------------------------------------------------
    if q in ("pause spotify", "stop spotify", "spotify pause"):
        from smart_home import spotify_pause

        return _speakable_result(spotify_pause())

    if q in ("what's playing", "whats playing", "now playing", "spotify status"):
        from smart_home import spotify_now_playing

        res = spotify_now_playing()
        if res.get("ok") and res.get("playing"):
            playing = res["playing"]
            device = res.get("device")
            if device:
                return f"Playing {playing} on {device}."
            return f"Playing {playing}."
        if res.get("ok"):
            return "Nothing is playing on Spotify."
        return _speakable_result(res)

    m = re.match(r"^(?:play|spotify play)\s+(.+)$", q)
    if m:
        from smart_home import spotify_play

        return _speakable_result(spotify_play(query=m.group(1).strip()))

    m = re.match(r"^play\s+(.+?)\s+on\s+spotify$", q)
    if m:
        from smart_home import spotify_play

        return _speakable_result(spotify_play(query=m.group(1).strip()))

    m = re.match(r"^(?:spotify to|play on|transfer to)\s+(.+)$", q)
    if m:
        from smart_home import spotify_transfer

        return _speakable_result(spotify_transfer(m.group(1).strip()))

    # --- macOS Music fallback ----------------------------------------------
    if q in ("pause music", "stop music", "pause the music"):
        try:
            import mac_automation as m

            return _speakable_result(m.music_pause())
        except Exception:
            return None

    if q in ("play music", "resume music", "continue music"):
        try:
            import mac_automation as m

            return _speakable_result(m.music_play())
        except Exception:
            return None

    if q in ("next song", "next track", "skip song", "skip track"):
        try:
            import mac_automation as m

            return _speakable_result(m.music_next())
        except Exception:
            return None

    if q in ("previous song", "previous track", "last song", "last track"):
        try:
            import mac_automation as m

            return _speakable_result(m.music_previous())
        except Exception:
            return None

    m = re.match(r"^play music\s+(.+)$", q)
    if m:
        try:
            import mac_automation as m

            return _speakable_result(m.music_search_and_play(m.group(1).strip()))
        except Exception:
            return None

    # --- HomeKit / Shortcuts scenes ----------------------------------------
    scene_triggers = (
        "good night",
        "goodnight",
        "movie mode",
        "movie time",
        "i'm home",
        "im home",
        "leaving home",
        "leave home",
        "focus mode",
        "work mode",
    )
    if q in scene_triggers:
        from smart_home import homekit_set_scene

        return _speakable_result(homekit_set_scene(q))

    m = re.match(r"^(?:set scene|run scene|activate scene|scene)\s+(.+)$", q)
    if m:
        from smart_home import homekit_set_scene

        return _speakable_result(homekit_set_scene(m.group(1).strip()))

    m = re.match(r"^(?:turn on|switch on)\s+(?:the\s+)?(.+?)(?:\s+light)?$", q)
    if m and "light" in q:
        from smart_home import homekit_set_light

        return _speakable_result(homekit_set_light(m.group(1).strip(), on=True))

    m = re.match(r"^(?:turn off|switch off)\s+(?:the\s+)?(.+?)(?:\s+light)?$", q)
    if m and "light" in q:
        from smart_home import homekit_set_light

        return _speakable_result(homekit_set_light(m.group(1).strip(), on=False))

    m = re.match(r"^dim(?:\s+the)?\s+(.+?)(?:\s+light)?(?:\s+to\s+(\d+))?$", q)
    if m:
        from smart_home import homekit_set_light

        pct = int(m.group(2) or 40)
        return _speakable_result(
            homekit_set_light(m.group(1).strip(), on=True, brightness=pct)
        )

    if q in ("list home scenes", "homekit scenes", "list scenes"):
        from smart_home import list_homekit_scenes

        scenes = list_homekit_scenes()
        if not scenes:
            return "No HomeKit scenes configured."
        return "Scenes: " + ", ".join(scenes)

    return None


__all__ = ["try_handle_smart_home"]
