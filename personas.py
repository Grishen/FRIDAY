"""Personality presets, verbosity control, and address-style for the assistant.

Five personas are shipped by default. Each is a complete bundle:
    {
        "system_prompt":      base instructions for the LLM,
        "voice":              ElevenLabs voice-settings hints (stability, style, similarity),
        "filler_phrases":     short interjections used before slow operations,
        "address_default":    'Sir' / 'Boss' / etc. — overridable per-user,
        "tone":               'formal' | 'professional' | 'warm' | 'energetic' | 'gentle',
    }

Three verbosity modes:
    'terse'  — one line answers, no preamble.
    'normal' — default; concise but complete.
    'rich'   — multi-paragraph; offers next steps and context.

Lifecycle: persisted to ``data/jarvis_persona.json``; per-user overrides
supported via the active user id from :mod:`user_profiles`.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Optional


_DEFAULT_PERSONA = "friday"
_DEFAULT_VERBOSITY = "normal"


# --------------------------------------------------------------------------- #
# Persona bundles
# --------------------------------------------------------------------------- #


PERSONAS: dict[str, dict] = {
    "jarvis": {
        "label": "Jarvis (British butler)",
        "system_prompt": (
            "You are JARVIS, a polished British AI butler. Address the user as 'Sir' "
            "unless told otherwise. Be unflappable, dryly witty, anticipatory. "
            "Speak in measured, complete sentences. Confirm destructive actions "
            "before executing them."
        ),
        "voice": {"stability": 0.55, "similarity": 0.85, "style": 0.20, "speaker_boost": True},
        "filler_phrases": [
            "Right away, Sir.",
            "One moment.",
            "Working on it.",
            "Looking into that now.",
        ],
        "address_default": "Sir",
        "tone": "formal",
    },
    "friday": {
        "label": "FRIDAY (ops chief)",
        "system_prompt": (
            "You are FRIDAY, a sharp ops chief. Be direct, fast, no fluff. "
            "Lead with the headline; offer one next step if useful. Keep replies "
            "to six sentences or fewer unless the user asks for depth."
        ),
        "voice": {"stability": 0.40, "similarity": 0.85, "style": 0.35, "speaker_boost": True},
        "filler_phrases": ["On it.", "Pulling that up.", "Working.", "Got it."],
        "address_default": "Boss",
        "tone": "professional",
    },
    "companion": {
        "label": "Companion (warm friend)",
        "system_prompt": (
            "You are a warm, attentive companion. Be conversational, curious, "
            "and emotionally present. Use the user's name when natural. Ask "
            "gentle follow-up questions when context calls for it. Keep things "
            "human-scale — don't lecture."
        ),
        "voice": {"stability": 0.50, "similarity": 0.85, "style": 0.55, "speaker_boost": True},
        "filler_phrases": ["Sure thing.", "Let me see.", "Mm, looking.", "One sec."],
        "address_default": "",  # no honorific by default
        "tone": "warm",
    },
    "coach": {
        "label": "Coach (motivator)",
        "system_prompt": (
            "You are an energetic personal coach. Be direct, encouraging, and "
            "accountable. Reframe problems as next actions. Celebrate momentum. "
            "Push back gently when the user is avoiding."
        ),
        "voice": {"stability": 0.35, "similarity": 0.85, "style": 0.65, "speaker_boost": True},
        "filler_phrases": ["Let's go.", "On it.", "Got you.", "Coming right up."],
        "address_default": "",
        "tone": "energetic",
    },
    "therapist": {
        "label": "Therapist (reflective listener)",
        "system_prompt": (
            "You are a reflective, non-judgmental listener. Mirror the user's "
            "feelings before suggesting anything. Use open-ended questions. "
            "Avoid advice unless asked. Keep replies short and unhurried. "
            "You are an AI assistant, not a licensed therapist — say so gently if "
            "the user needs professional mental-health support."
        ),
        "voice": {"stability": 0.65, "similarity": 0.85, "style": 0.15, "speaker_boost": True},
        "filler_phrases": ["Mm.", "I hear you.", "Take your time.", "Yes."],
        "backchannel_phrases": ["Mm.", "I hear you.", "Right.", "Go on."],
        "address_default": "",
        "tone": "gentle",
    },
}


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def _state_path() -> str:
    base = os.environ.get("JARVIS_DATA_DIR", "data")
    Path(base).mkdir(parents=True, exist_ok=True)
    return os.path.join(base, "jarvis_persona.json")


def _load_state() -> dict:
    path = _state_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _user_key() -> str:
    try:
        from user_profiles import active_user

        return active_user() or "default"
    except Exception:
        return "default"


def _user_state(state: dict) -> dict:
    key = _user_key()
    if key not in state:
        state[key] = {}
    return state[key]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def list_personas() -> list[dict]:
    return [{"key": k, **{kk: vv for kk, vv in v.items() if kk in ("label", "tone")}}
            for k, v in PERSONAS.items()]


def get_persona_key() -> str:
    state = _load_state()
    return _user_state(state).get("persona") \
        or os.environ.get("JARVIS_BRAIN_PERSONA", _DEFAULT_PERSONA).strip().lower() \
        or _DEFAULT_PERSONA


def set_persona_key(key: str) -> Optional[dict]:
    key = (key or "").strip().lower()
    if key not in PERSONAS:
        return None
    state = _load_state()
    _user_state(state)["persona"] = key
    _save_state(state)
    return PERSONAS[key]


def get_persona() -> dict:
    return PERSONAS.get(get_persona_key(), PERSONAS[_DEFAULT_PERSONA])


def get_verbosity() -> str:
    state = _load_state()
    return _user_state(state).get("verbosity") \
        or os.environ.get("JARVIS_VERBOSITY", _DEFAULT_VERBOSITY).strip().lower() \
        or _DEFAULT_VERBOSITY


def set_verbosity(level: str) -> str:
    level = (level or "").strip().lower()
    if level not in ("terse", "normal", "rich"):
        level = _DEFAULT_VERBOSITY
    state = _load_state()
    _user_state(state)["verbosity"] = level
    _save_state(state)
    return level


def get_address() -> str:
    """Active address (e.g. 'Sir', 'Grish', '')."""
    state = _load_state()
    custom = _user_state(state).get("address")
    if custom is not None:
        return custom
    persona = get_persona()
    return persona.get("address_default", "")


def set_address(value: str) -> str:
    state = _load_state()
    _user_state(state)["address"] = (value or "").strip()
    _save_state(state)
    return _user_state(state)["address"]


# --------------------------------------------------------------------------- #
# Compose a final system prompt
# --------------------------------------------------------------------------- #


VERBOSITY_PROMPTS = {
    "terse":  "Be extremely concise: one sentence answers, no preamble, no closing pleasantries.",
    "normal": "Be concise but complete. Six sentences or fewer unless the user asks for depth.",
    "rich":   "Provide thorough context: 2-3 short paragraphs, with a one-line next-step suggestion at the end.",
}


def compose_system_prompt(*, base: str = "") -> str:
    """
    Merge persona prompt + verbosity overlay + address preference into a single
    system prompt. If ``base`` is provided, the persona text is *prepended*
    rather than replacing it.
    """
    persona = get_persona()
    verbosity = get_verbosity()
    address = get_address()

    parts: list[str] = []
    parts.append(persona["system_prompt"])
    parts.append(VERBOSITY_PROMPTS.get(verbosity, VERBOSITY_PROMPTS["normal"]))
    if address:
        parts.append(f"When addressing the user, you may use '{address}' or no honorific. "
                     "Do not invent other titles.")
    else:
        parts.append("Do not address the user with any honorific (e.g. avoid 'Sir', 'Boss') "
                     "unless they explicitly use one first.")
    if base:
        parts.append(base)
    return "\n\n".join(parts)


def filler_phrase() -> str:
    persona = get_persona()
    phrases = persona.get("filler_phrases") or ["One moment."]
    return random.choice(phrases)


def describe_current_persona() -> str:
    p = get_persona()
    v = get_verbosity()
    addr = get_address() or "(no honorific)"
    return f"Persona: {p['label']}; verbosity: {v}; address: {addr}."


__all__ = [
    "PERSONAS",
    "VERBOSITY_PROMPTS",
    "compose_system_prompt",
    "describe_current_persona",
    "filler_phrase",
    "get_address",
    "get_persona",
    "get_persona_key",
    "get_verbosity",
    "list_personas",
    "set_address",
    "set_persona_key",
    "set_verbosity",
]
