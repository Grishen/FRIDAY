# All Packages to Import

# pip install pyttsx3
# pip install SpeechRecognition
# pip install pipwin
# pipwin install pyaudio
# pip install pywhatkit
# pip install PyAutoGUI
# pip install wolframalpha
# pip install wikipedia
# pip install git+https://github.com/abenassi/Google-Search-API
# pip install playsound
# pip install speedtest-cli
# pip install psutil
# pip install pyjokes

# Python Test to Speech Package
import operator
import re
import sys
import threading
import traceback
from typing import Optional

import pyttsx3
# Package to Recognise the Speech
import speech_recognition as sr
from speech_recognition.exceptions import WaitTimeoutError
# For Date and Time
import datetime
# For Opening the Applications
import os
# Open any Website
import webbrowser
# To Play Song on YouTube
import pywhatkit
# To Increase/Decrease the System Volume
import pyautogui
# For Opening any System Application [Calculator]
from subprocess import call
import subprocess
import shutil
from urllib.parse import quote_plus
# For Searching Anything
import wolframalpha
# For Searching Something in Wikipedia
import wikipedia
# For Searching via Google API
import googleapi
from googleapi import google
# For Weather
import requests
import json
# For Internet Speed
import speedtest
# For Internet Availibility
import urllib.request
# For Memory Usage
import psutil
# For Jokes
import pyjokes
# For Delay
import time

import elevenlabs_tts

from jarvis_exceptions import JarvisExitRequest
from knowledge.voice_triggers import (
    extract_kb_question,
    extract_learn_text,
    extract_url,
    wants_knowledge_lookup,
    wants_learn_knowledge,
)

try:
    from knowledge.rag_store import answer_from_knowledge, sync_knowledge_folder
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

try:
    import jarvis_brain as jb
except ImportError:
    jb = None  # type: ignore[assignment, misc]

_tls = threading.local()

# Pending destructive-memory action, confirmed by user.
_pending_forget: Optional[dict[str, str]] = None


def register_voice_ui_hooks(*, on_listening=None, on_heard=None) -> None:
    """Optional callbacks for a GUI shell (set from the same thread that runs the voice loop)."""
    if on_listening or on_heard:
        _tls.voice_hooks = {"on_listening": on_listening, "on_heard": on_heard}
    elif hasattr(_tls, "voice_hooks"):
        del _tls.voice_hooks


# Voice Initialization Part for Jarvis

# Helps in synthesis and recognition of voice.
# sapi5 is Windows-only; macOS uses nsss (NSSpeechSynthesizer); Linux typically uses espeak.
if sys.platform == "win32":
    engine = pyttsx3.init("sapi5")
elif sys.platform == "darwin":
    engine = pyttsx3.init("nsss")
else:
    engine = pyttsx3.init()
voices = engine.getProperty("voices")
# print(voices[0].id) # [0 -> David, 1 -> Zira]
if voices:
    engine.setProperty("voice", voices[0].id)
    _vsub = os.environ.get("JARVIS_PYTTSX3_VOICE_SUBSTRING", "").strip()
    if _vsub:
        _low = _vsub.lower()
        for v in voices:
            blob = f"{getattr(v, 'name', '')} {getattr(v, 'id', '')}".lower()
            if _low in blob:
                engine.setProperty("voice", v.id)
                break

def _report_tts_backend() -> None:
    """Print which TTS backend will be used so misconfiguration is visible at startup."""
    force_local = os.environ.get("JARVIS_USE_LOCAL_TTS", "").lower() in ("1", "true", "yes")
    eleven_only = os.environ.get("JARVIS_ELEVENLABS_ONLY", "").lower() in ("1", "true", "yes")
    env_src = elevenlabs_tts.loaded_env_path() or "(none — using process env only)"
    print(f"[startup] env loaded from: {env_src}")

    if force_local:
        print("[startup] TTS: pyttsx3 (forced by JARVIS_USE_LOCAL_TTS=1)")
        return
    if elevenlabs_tts.is_configured():
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")[:8]
        print(f"[startup] TTS: ElevenLabs (voice_id={voice_id}…)")
        return
    if eleven_only:
        print(
            "[startup] TTS: NONE — JARVIS_ELEVENLABS_ONLY=1 but ElevenLabs is not configured. "
            "Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID."
        )
        return
    try:
        import jarvis_edge_tts as jet

        if jet.edge_enabled() and jet.is_available():
            print("[startup] TTS: edge-tts (Microsoft neural)")
            return
    except Exception:
        pass
    print("[startup] TTS: pyttsx3 (offline fallback — ElevenLabs/edge-tts not configured)")


_report_tts_backend()


def _report_voice_io_backends() -> None:
    try:
        from stt_capture import describe_runtime, has_capture_backend
    except Exception as exc:
        print(f"[startup] STT runtime: unavailable ({exc})")
        return
    if not has_capture_backend():
        print("[startup] STT capture: no `sounddevice` or `pyaudio` installed — "
              "falling back to legacy speech_recognition (Google).")
        return
    print(f"[startup] STT runtime: {describe_runtime()}")


_report_voice_io_backends()


# Function to Convert Text to Speech
# Chain (unless JARVIS_USE_LOCAL_TTS=1): ElevenLabs → Microsoft neural (edge-tts, online) → pyttsx3 offline.
# Use your ElevenLabs cloned voice: set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID
# (optional: ELEVENLABS_MODEL_ID, ELEVENLABS_OUTPUT_FORMAT, ELEVENLABS_API_BASE).
# Optional .env in project root is read if python-dotenv is installed.
# Free neural online: pip install edge-tts; JARVIS_EDGE_TTS_VOICE=en-US-AriaNeural (see edge-tts --list-voices).
# Offline Windows: install better SAPI voices in Settings; optional JARVIS_PYTTSX3_VOICE_SUBSTRING=David
# Set JARVIS_USE_LOCAL_TTS=1 to force pyttsx3 only.
# Set JARVIS_ELEVENLABS_ONLY=1 when ElevenLabs is configured — no other fallbacks on success path.


_speak_lock = threading.Lock()
_speak_stop = threading.Event()
_speak_thread: Optional[threading.Thread] = None
_speak_remember = True
_last_capture_info: dict = {}
_speaker_announced_users: set[str] = set()


def _streaming_tts_enabled() -> bool:
    return os.environ.get("JARVIS_STREAM_TTS", "1").strip().lower() not in ("0", "false", "no", "off")


def get_last_capture_info() -> dict:
    return dict(_last_capture_info)


def speak_reply(text: str) -> None:
    """Speak assistant replies — streaming + mood-aware voice when enabled."""
    force_local = os.environ.get("JARVIS_USE_LOCAL_TTS", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    # Local pyttsx3 must use the main-thread engine — streaming init() per chunk breaks on macOS.
    if force_local or not _streaming_tts_enabled():
        speak(str(text))
    else:
        speak_streaming(str(text))


def stop_speaking() -> None:
    """Interrupt any currently-playing TTS playback (barge-in)."""
    _speak_stop.set()
    try:
        engine.stop()
    except Exception:
        pass


def _is_speaking() -> bool:
    t = _speak_thread
    return bool(t and t.is_alive())


def _speak_blocking(text: str) -> None:
    force_local = os.environ.get("JARVIS_USE_LOCAL_TTS", "").lower() in ("1", "true", "yes")
    eleven_only = os.environ.get("JARVIS_ELEVENLABS_ONLY", "").lower() in ("1", "true", "yes")
    if _speak_stop.is_set():
        return
    if not force_local and elevenlabs_tts.is_configured():
        try:
            if elevenlabs_tts.synthesize_and_play(text):
                return
        except Exception as exc:
            print(f"ElevenLabs TTS failed ({exc}).")
            if not eleven_only:
                print("Falling back to other TTS.")
        if eleven_only:
            return
    if eleven_only and not elevenlabs_tts.is_configured():
        print("JARVIS_ELEVENLABS_ONLY is set but ElevenLabs is not configured; cannot speak.")
        return
    if _speak_stop.is_set():
        return
    if not force_local:
        try:
            import jarvis_edge_tts as jet

            if jet.edge_enabled() and jet.is_available():
                jet.synthesize_and_play(text)
                return
        except Exception as exc:
            print(f"Edge neural TTS failed ({exc}); using offline pyttsx3.")
    if _speak_stop.is_set():
        return
    engine.say(text)
    engine.runAndWait()


def speak_streaming(text: str) -> None:
    """
    Speak ``text`` using sentence-by-sentence streaming TTS so audio starts
    almost immediately. Falls back to the regular speak() on failure.
    """
    print("Command: " + text)
    if _speak_remember:
        try:
            from memory.episodic_memory import memory_append_turn

            memory_append_turn("assistant", str(text))
        except Exception:
            pass
        try:
            from dialogue_state import remember_last_reply

            remember_last_reply(str(text))
        except Exception:
            pass

    stop_speaking()
    try:
        from tts_stream import speak_stream_text

        _speak_stop.clear()
        speak_stream_text(str(text), stop_event=_speak_stop)
        return
    except Exception as exc:
        print(f"Streaming TTS failed ({exc}); using non-streaming speak.")
    speak(text)


def speak(text):
    global _speak_thread
    print("Command: " + text)
    if _speak_remember:
        try:
            from memory.episodic_memory import memory_append_turn

            memory_append_turn("assistant", str(text))
        except Exception:
            pass
        try:
            from dialogue_state import remember_last_reply

            remember_last_reply(str(text))
        except Exception:
            pass

    # Interrupt any prior speech immediately so a new utterance never overlaps.
    stop_speaking()
    if _speak_thread and _speak_thread.is_alive():
        _speak_thread.join(timeout=0.4)

    with _speak_lock:
        _speak_stop.clear()
        t = threading.Thread(target=_speak_blocking, args=(str(text),), daemon=True)
        _speak_thread = t
        t.start()
    # Block until done so callers keep linear flow (barge-in still works because
    # any new call to speak() or stop_speaking() flips _speak_stop).
    t.join()


_FILLER_PHRASES = (
    "One moment, Sir.",
    "Looking into that.",
    "Working on it.",
    "Just a second.",
    "Pulling that up now.",
)


def speak_filler() -> None:
    """Speak a quick acknowledgment before slow operations; non-blocking and best-effort."""
    if os.environ.get("JARVIS_DISABLE_FILLER", "").strip().lower() in ("1", "true", "yes"):
        return
    try:
        from mood_trajectory import should_suppress_cheerful_filler

        if should_suppress_cheerful_filler():
            return
    except Exception:
        pass
    import random

    phrase: str
    try:
        from personas import filler_phrase as _persona_filler

        phrase = _persona_filler()
    except Exception:
        phrase = random.choice(_FILLER_PHRASES)
    global _speak_remember
    try:
        _speak_remember = False
        speak(phrase)
    finally:
        _speak_remember = True

def _listen_timeout_seconds():
    """Seconds to wait for speech to *begin*. None = wait indefinitely (idle until you speak)."""
    raw = os.environ.get("JARVIS_LISTEN_TIMEOUT", "").strip().lower()
    if raw in ("", "none", "inf", "infinity"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _phrase_time_limit_seconds():
    raw = os.environ.get("JARVIS_PHRASE_SECONDS", "").strip()
    if raw == "":
        return 15.0
    try:
        return float(raw)
    except ValueError:
        return 15.0


def _wake_words() -> list[str]:
    raw = os.environ.get("JARVIS_WAKE_WORD", "jarvis,hey jarvis,friday,hey friday").strip()
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def _passive_mode_enabled() -> bool:
    return os.environ.get("JARVIS_PASSIVE_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def _strip_wake_prefix(raw: str) -> tuple[bool, str]:
    """Return (had_wake_word, utterance_after_wake_word)."""
    low = (raw or "").strip().lower()
    if not low:
        return False, ""
    for w in sorted(_wake_words(), key=len, reverse=True):
        if low == w:
            return True, ""
        if low.startswith(w + " "):
            return True, raw[len(w) + 1 :].strip()
        if low.startswith(w + ",") or low.startswith(w + "."):
            return True, raw[len(w) + 1 :].strip()
    return False, raw


_hotkey_signal = threading.Event()


def _user_voice_command(query: str) -> bool:
    try:
        from user_profiles import parse_user_command

        intent, _ = parse_user_command(query)
        return intent in ("switch", "who", "list")
    except Exception:
        return False


# --- Vision voice triggers ---------------------------------------------------

_WEBCAM_TRIGGERS = (
    "take a picture",
    "take a photo",
    "take a selfie",
    "snap a picture",
    "snap a photo",
    "use the camera",
    "use my camera",
    "use the webcam",
    "look at me",
    "look at my face",
    "what do you see",
    "see me",
    "open the camera",
)

_CLIPBOARD_TRIGGERS = (
    "describe clipboard",
    "describe the clipboard",
    "describe my clipboard",
    "what's in my clipboard",
    "what is in my clipboard",
    "what's on my clipboard",
    "look at my clipboard",
    "read clipboard image",
)

_IMAGE_FILE_TRIGGERS = (
    "describe image ",
    "describe the image ",
    "describe picture ",
    "describe photo ",
    "look at image ",
    "look at the image ",
    "look at picture ",
    "look at photo ",
    "look at file ",
    "open image ",
    "what is in the image ",
    "what's in the image ",
)

_FOLLOWUP_TRIGGERS = (
    "about the image",
    "about that image",
    "about that picture",
    "about that photo",
    "about the picture",
    "about the photo",
    "about the screenshot",
    "about that screenshot",
    "in that image",
    "in the image",
    "in that picture",
    "in the picture",
    "in that photo",
    "in the photo",
    "in that screenshot",
    "from the picture",
    "from the photo",
    "from that image",
    "from that picture",
    "from that photo",
)


def _vision_webcam_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _WEBCAM_TRIGGERS)


def _vision_clipboard_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _CLIPBOARD_TRIGGERS)


def _vision_image_file_command(query: str) -> bool:
    q = query.lower()
    return any(q.startswith(t) for t in _IMAGE_FILE_TRIGGERS)


def _vision_followup_command(query: str) -> bool:
    q = query.lower().strip()
    return any(t in q for t in _FOLLOWUP_TRIGGERS)


def _extract_vision_prompt(query: str, triggers: tuple[str, ...]) -> str:
    """
    Pull out any trailing instruction after a trigger phrase, e.g.:
      "take a picture and tell me what color my shirt is"
        → "tell me what color my shirt is"
    Returns empty string if no follow-up is present (caller picks a default prompt).
    """
    q = query.strip()
    low = q.lower()
    # Cut after the *latest* matching trigger.
    cut = 0
    for t in triggers:
        idx = low.find(t)
        if idx >= 0:
            end = idx + len(t)
            if end > cut:
                cut = end
    remainder = q[cut:].strip() if cut else q
    # Strip bridging words repeatedly (handles ", then ", "and then ", etc.).
    bridges = ("and then ", "and ", "then ", "so ", "now ", ", ", ". ")
    changed = True
    while changed:
        changed = False
        low_r = remainder.lower().lstrip(" ,.;")
        offset = len(remainder) - len(remainder.lstrip(" ,.;"))
        for lead in bridges:
            if low_r.startswith(lead):
                remainder = remainder[offset + len(lead):]
                changed = True
                break
    return remainder.strip(" ,.;")


def _parse_image_file_command(query: str) -> tuple[str, str]:
    """
    Parse `describe image /path/to/foo.jpg [optional question]`.
    Returns (path, prompt). Path is empty if it couldn't be extracted.
    """
    q = query.strip()
    low = q.lower()
    for t in _IMAGE_FILE_TRIGGERS:
        if low.startswith(t):
            rest = q[len(t):].strip()
            if not rest:
                return "", ""
            if rest.startswith(("'", '"')):
                quote = rest[0]
                end = rest.find(quote, 1)
                if end == -1:
                    return rest[1:], ""
                return rest[1:end], rest[end + 1 :].strip(" ,.")
            parts = rest.split(None, 1)
            path = parts[0]
            prompt = parts[1].strip(" ,.") if len(parts) > 1 else ""
            prompt = _extract_vision_prompt(prompt, ()) if prompt else ""
            return path, prompt
    return "", ""


# --- Advanced vision triggers ------------------------------------------------

_COMPARE_TRIGGERS = (
    "compare the last two",
    "compare those two",
    "compare these two",
    "compare those pictures",
    "compare those images",
    "compare those photos",
    "compare them",
    "what changed between",
    "diff the images",
    "diff the pictures",
)

_READ_TEXT_TRIGGERS = (
    "read the text",
    "extract the text",
    "extract text from",
    "ocr the",
    "what does it say",
    "what does that say",
    "transcribe the text",
    "read what's on",
    "read what is on",
)

_OBJECTS_TRIGGERS = (
    "what objects are in",
    "what's in the image",
    "what is in the image",
    "find objects in",
    "detect objects",
    "label everything",
    "what objects do you see",
    "what do you see in",
)

_MOTION_TRIGGERS = (
    "watch me for",
    "watch me",
    "look at me for",
    "record me for",
    "what am i doing",
    "watch what i'm doing",
    "what am i doing right now",
)

_PDF_TRIGGERS = (
    "analyze pdf ",
    "analyse pdf ",
    "describe pdf ",
    "read pdf ",
    "summarize pdf ",
    "summarise pdf ",
    "what's in pdf ",
    "what is in pdf ",
)

_RECENT_DOWNLOAD_TRIGGERS = (
    "look at my recent download",
    "look at the recent download",
    "describe my recent download",
    "what did i just download",
    "look at the picture i just downloaded",
    "look at the image i just downloaded",
    "analyze my recent download",
    "describe my latest download",
)

_GENERATE_TRIGGERS = (
    "generate an image of ",
    "generate an image ",
    "create an image of ",
    "create an image ",
    "make an image of ",
    "draw an image of ",
    "draw a picture of ",
    "render an image of ",
)

_URL_TRIGGERS = (
    "look at https://",
    "look at http://",
    "describe https://",
    "describe http://",
    "analyze https://",
    "analyze http://",
    "open https://",
    "open http://",
    "what's at https://",
    "what is at https://",
)


def _vision_compare_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _COMPARE_TRIGGERS)


def _vision_read_text_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _READ_TEXT_TRIGGERS)


def _vision_read_text_target(query: str) -> str:
    q = query.lower()
    if "screen" in q or "desktop" in q:
        return "screen"
    if "clipboard" in q or "what i copied" in q:
        return "clipboard"
    if "camera" in q or "webcam" in q or "in front of me" in q:
        return "camera"
    return "last"


def _vision_objects_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _OBJECTS_TRIGGERS)


def _vision_objects_target(query: str) -> str:
    q = query.lower()
    if "screen" in q or "desktop" in q:
        return "screen"
    if "camera" in q or "webcam" in q or "in front of me" in q:
        return "camera"
    return "last"


def _vision_motion_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _MOTION_TRIGGERS)


def _vision_motion_seconds(query: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b", query.lower())
    if m:
        try:
            return max(1.0, min(8.0, float(m.group(1))))
        except ValueError:
            pass
    return 2.0


def _vision_pdf_command(query: str) -> bool:
    q = query.lower()
    return any(q.startswith(t) for t in _PDF_TRIGGERS)


def _parse_vision_pdf_command(query: str) -> tuple[str, str]:
    q = query.strip()
    low = q.lower()
    for t in _PDF_TRIGGERS:
        if low.startswith(t):
            rest = q[len(t):].strip()
            if not rest:
                return "", ""
            if rest.startswith(("'", '"')):
                quote = rest[0]
                end = rest.find(quote, 1)
                if end == -1:
                    return rest[1:], ""
                return rest[1:end], rest[end + 1 :].strip(" ,.")
            parts = rest.split(None, 1)
            path = parts[0]
            prompt = _extract_vision_prompt(parts[1], ()) if len(parts) > 1 else ""
            return path, prompt
    return "", ""


def _vision_recent_download_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _RECENT_DOWNLOAD_TRIGGERS)


def _vision_generate_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _GENERATE_TRIGGERS)


def _parse_vision_generate_command(query: str) -> str:
    q = query.strip()
    low = q.lower()
    for t in _GENERATE_TRIGGERS:
        if low.startswith(t):
            return q[len(t):].strip(" .,!?")
    # 'and generate an image of …' mid-sentence
    for t in _GENERATE_TRIGGERS:
        idx = low.find(t)
        if idx >= 0:
            return q[idx + len(t):].strip(" .,!?")
    return ""


def _vision_url_command(query: str) -> bool:
    q = query.lower()
    return any(t in q for t in _URL_TRIGGERS)


def _parse_vision_url_command(query: str) -> tuple[str, str]:
    m = re.search(r"https?://\S+", query)
    if not m:
        return "", ""
    url = m.group(0).rstrip(".,;)\"'")
    tail = query[m.end():].strip(" ,.;:")
    prompt = _extract_vision_prompt(tail, ()) if tail else ""
    return url, prompt


# --- Sound monitor lifecycle (package C) -------------------------------------

_sound_monitor = None  # lazily-instantiated SoundMonitor
_live_camera = None
_live_screen = None


def _on_sound_event(event) -> None:
    """Callback the sound monitor invokes on a loud burst."""
    try:
        from ambient import is_snoozed

        if is_snoozed("sound"):
            return
    except Exception:
        pass
    try:
        try:
            from personas import get_address

            addr = get_address() or "Sir"
        except Exception:
            addr = "Sir"
        kind = getattr(event, "kind", "burst")
        transcript = (getattr(event, "transcript", "") or "").strip()
        if kind == "doorbell":
            speak_reply(f"{addr}, I think I heard the doorbell.")
        elif kind == "alarm":
            speak_reply(f"{addr}, an alarm is going off.")
        elif kind == "phone":
            speak_reply(f"{addr}, sounds like the phone is ringing.")
        elif kind == "speech" and transcript:
            speak_reply(f"Did you say something, {addr}? I heard: {transcript}")
        else:
            if os.environ.get("JARVIS_SOUND_ALERT_BURSTS", "0").lower() in ("1", "true", "yes"):
                speak_reply(f"{addr}, I heard a loud sound.")
    except Exception:
        pass


def _sound_monitor_auto_enabled() -> bool:
    raw = os.environ.get("JARVIS_SOUND_MONITOR", "auto").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _start_sound_monitor() -> bool:
    global _sound_monitor
    try:
        from sound_monitor import SoundMonitor, register_global
    except Exception:
        return False
    if _sound_monitor and _sound_monitor.is_running():
        return True
    _sound_monitor = SoundMonitor(on_event=_on_sound_event)
    ok = _sound_monitor.start()
    if ok:
        register_global(_sound_monitor)
    return ok


_PERSONA_SWITCH_PHRASES = (
    "switch persona to ", "switch to ", "be ", "act like ", "use persona ",
    "change persona to ", "become ",
)


def _persona_switch_command(query: str) -> bool:
    q = query.lower()
    try:
        from personas import PERSONAS

        keys = list(PERSONAS.keys())
    except Exception:
        keys = ["jarvis", "friday", "companion", "coach", "therapist"]
    for prefix in _PERSONA_SWITCH_PHRASES:
        if q.startswith(prefix):
            tail = q[len(prefix):].strip()
            if any(tail.startswith(k) or tail == k for k in keys):
                return True
    return False


def _persona_switch_target(query: str) -> str:
    q = query.lower()
    try:
        from personas import PERSONAS

        keys = list(PERSONAS.keys())
    except Exception:
        keys = ["jarvis", "friday", "companion", "coach", "therapist"]
    for prefix in _PERSONA_SWITCH_PHRASES:
        if q.startswith(prefix):
            tail = q[len(prefix):].strip()
            for k in keys:
                if tail == k or tail.startswith(k + " ") or tail.startswith(k + "."):
                    return k
    return ""


def _stop_sound_monitor() -> bool:
    global _sound_monitor
    if _sound_monitor is None:
        return False
    was_running = _sound_monitor.is_running()
    _sound_monitor.stop()
    _sound_monitor = None
    return was_running


def _start_live_camera() -> bool:
    global _live_camera
    try:
        from live_observers import LiveCameraObserver
    except Exception:
        return False
    if _live_camera and _live_camera.is_running():
        return True
    _live_camera = LiveCameraObserver(on_event=speak)
    return _live_camera.start()


def _stop_live_camera() -> bool:
    global _live_camera
    if _live_camera is None:
        return False
    was = _live_camera.is_running()
    _live_camera.stop()
    _live_camera = None
    return was


def _start_live_screen() -> bool:
    global _live_screen
    try:
        from live_observers import LiveScreenObserver
    except Exception:
        return False
    if _live_screen and _live_screen.is_running():
        return True
    _live_screen = LiveScreenObserver(on_event=speak)
    return _live_screen.start()


def _stop_live_screen() -> bool:
    global _live_screen
    if _live_screen is None:
        return False
    was = _live_screen.is_running()
    _live_screen.stop()
    _live_screen = None
    return was


def _start_hotkey_listener() -> None:
    """Optional: bind a global hotkey (needs `pynput`). Sets _hotkey_signal when pressed."""
    spec = os.environ.get("JARVIS_HOTKEY", "").strip()
    if not spec:
        return
    try:
        from pynput import keyboard  # type: ignore
    except Exception:
        print("Hotkey requested but pynput is not installed. pip install pynput")
        return

    def _on_activate() -> None:
        _hotkey_signal.set()

    try:
        hk = keyboard.GlobalHotKeys({spec: _on_activate})
        hk.daemon = True
        hk.start()
        print(f"Global hotkey active: {spec} (press to wake Jarvis).")
    except Exception as exc:  # noqa: BLE001
        print(f"Hotkey setup failed: {exc}")


def _use_whisper_capture() -> bool:
    """Whisper + VAD capture is used when JARVIS_USE_WHISPER is truthy and deps exist."""
    flag = os.environ.get("JARVIS_USE_WHISPER", "auto").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    try:
        from stt_capture import has_capture_backend
        from stt_whisper import available_backends

        if not has_capture_backend():
            return False
        avail = available_backends()
    except Exception:
        return False
    if flag in ("1", "true", "yes", "on"):
        return bool(avail)
    # auto: VAD capture when any non-Google STT exists, or always if only google.
    return bool(avail)


def _backchannel_speak(phrase: str) -> None:
    """Ultra-short acknowledgment; not stored as an assistant turn."""
    global _speak_remember
    try:
        _speak_remember = False
        speak(str(phrase))
    finally:
        _speak_remember = True


def _take_command_whisper() -> str:
    """VAD-streamed mic capture → Whisper STT (with graceful per-error fallback)."""
    from stt_capture import listen_once

    hooks = getattr(_tls, "voice_hooks", None)

    def _on_listen():
        print("listening… (Whisper + VAD)")
        if hooks and hooks.get("on_listening"):
            try:
                hooks["on_listening"]()
            except Exception:
                pass
        if _is_speaking():
            stop_speaking()

    def _on_started():
        if _is_speaking():
            stop_speaking()

    def _on_backchannel(elapsed_s: float) -> bool:
        try:
            from backchannels import maybe_backchannel

            return maybe_backchannel(elapsed_s, speak_fn=_backchannel_speak)
        except Exception:
            return False

    try:
        from backchannels import reset_utterance

        reset_utterance()
    except Exception:
        pass

    text, info = listen_once(
        on_listening=_on_listen,
        on_started=_on_started,
        on_backchannel=_on_backchannel,
    )
    global _last_capture_info
    _last_capture_info = dict(info or {})
    if info.get("error") == "start_timeout":
        print("No speech detected before timeout; speak again.")
        return "none"
    if not text:
        err = info.get("stt_error") or info.get("error") or ""
        if err:
            print(f"Speech recognition issue: {err}")
            low = err.lower()
            if any(x in low for x in ("quota", "429", "402", "billing", "payment")):
                speak(
                    "Sir, cloud speech recognition is unavailable — I'll use the free "
                    "fallback. Try again."
                )
                return "none"
        speak("Say that again please...")
        return "none"
    print(f"user said: {text}  [{info.get('stt_backend')}, "
          f"{info.get('duration_ms', 0)}ms audio]")
    if hooks and hooks.get("on_heard"):
        try:
            hooks["on_heard"](text)
        except Exception:
            pass
    return text


# Function to Take Command [Voice] From User and Convert to text
def take_command():
    if _use_whisper_capture():
        try:
            return _take_command_whisper()
        except Exception as exc:
            print(f"Whisper path failed ({exc}); falling back to Google STT.")

    hooks = getattr(_tls, "voice_hooks", None)
    if hooks and hooks.get("on_listening"):
        hooks["on_listening"]()
    r = sr.Recognizer()
    listen_timeout = _listen_timeout_seconds()
    phrase_limit = _phrase_time_limit_seconds()
    with sr.Microphone() as source:
        if listen_timeout is None:
            print("listening… (waiting until you speak)")
        else:
            print(f"listening… (timeout {listen_timeout}s for speech to start)")
        r.pause_threshold = 1
        try:
            try:
                r.adjust_for_ambient_noise(source, duration=0.3)
            except Exception:
                pass
            if _is_speaking():
                stop_speaking()
            audio = r.listen(source, timeout=listen_timeout, phrase_time_limit=phrase_limit)
            stop_speaking()
        except WaitTimeoutError:
            print("No speech detected before timeout; speak again.")
            return "none"
    try:
        print("Recognizing...")
        query = r.recognize_google(audio, language='en-in')
        print(f"user said: {query}")
        if hooks and hooks.get("on_heard"):
            hooks["on_heard"](query)
    except Exception as e:
        speak("Say that again please...")
        return "none"
    return query

# Function to Greet the User
def _time_greeting() -> str:
    hour = int(datetime.datetime.now().hour)
    if 0 <= hour <= 11:
        return "Good morning"
    if 12 <= hour <= 17:
        return "Good afternoon"
    return "Good evening"


def _apply_speaker_from_capture(info: dict) -> None:
    """Match voiceprint (+ optional face) → switch active user when confident."""
    flag = os.environ.get("JARVIS_SPEAKER_ID", "auto").strip().lower()
    face_flag = os.environ.get("JARVIS_FACE_ID", "0").strip().lower()
    if flag in ("0", "false", "no", "off") and face_flag in ("0", "false", "no", "off"):
        return
    pcm = info.get("pcm")
    sr = info.get("sample_rate")
    if not pcm or not sr:
        return
    try:
        if face_flag not in ("0", "false", "no", "off"):
            from identity_fusion import fuse_identity

            fused = fuse_identity(pcm, int(sr))
            if fused.get("switched"):
                uid = str(fused.get("user_id") or "")
                announce = os.environ.get("JARVIS_SPEAKER_ID_ANNOUNCE", "1").strip().lower()
                if announce not in ("0", "false", "no", "off") and uid and uid not in _speaker_announced_users:
                    _speaker_announced_users.add(uid)
                    try:
                        from personas import get_address

                        addr = get_address() or uid
                    except Exception:
                        addr = uid
                    speak_reply(f"Hi {addr}.")
            return

        from speaker_id import enroll_active_user, match_speaker
        from user_profiles import active_user, set_active_user

        match = match_speaker(pcm, int(sr))
        enroll_active_user(pcm, int(sr))

        uid = str(match.get("user_id") or "")
        if not uid or match.get("enrolled"):
            return

        current = active_user()
        try:
            threshold = float(os.environ.get("JARVIS_SPEAKER_THRESHOLD", "0.82"))
        except (TypeError, ValueError):
            threshold = 0.82

        if match.get("known") and uid != current:
            set_active_user(uid, display_name=uid)
            announce = os.environ.get("JARVIS_SPEAKER_ID_ANNOUNCE", "1").strip().lower()
            if announce not in ("0", "false", "no", "off") and uid not in _speaker_announced_users:
                _speaker_announced_users.add(uid)
                try:
                    from personas import get_address

                    addr = get_address() or uid
                except Exception:
                    addr = uid
                speak_reply(f"Hi {addr}.")
    except Exception:
        traceback.print_exc()


def _companion_ask(text: str) -> str:
    """Text-only brain path for phone / watch companion API."""
    q = (text or "").strip()
    if not q:
        return "Please send a question."
    try:
        from memory.episodic_memory import memory_build_context_for_prompt
        from jarvis_brain import brain_enabled, run_agent_brain

        if not brain_enabled():
            return "Brain is disabled on this device."
        ctx = memory_build_context_for_prompt(query=q, max_chars=4000)
        return run_agent_brain(user_utterance=q, episodic_prefill=ctx)
    except Exception as exc:
        return f"Could not answer: {exc}"


def _live_camera_auto() -> bool:
    return os.environ.get("JARVIS_LIVE_CAMERA", "").strip().lower() in ("auto", "1", "true", "yes", "on")


def _live_screen_auto() -> bool:
    return os.environ.get("JARVIS_LIVE_SCREEN", "").strip().lower() in ("auto", "1", "true", "yes", "on")


def greet():
    try:
        from personas import get_address, get_persona

        persona = get_persona()
        address = get_address()
        persona_label = persona.get("label", "FRIDAY")
    except Exception:
        address = "Sir"
        persona_label = "Jarvis"

    time_line = _time_greeting()
    if address:
        speak_reply(f"{time_line}, {address}.")
    else:
        speak_reply(f"{time_line}.")

    try:
        from memory.episodic_memory import (
            memory_list_profile_facts,
            memory_list_reflections,
            memory_list_summaries,
        )
        from sentiment import recent_mood_label

        facts = memory_list_profile_facts(max_facts=4)
        reflections = memory_list_reflections(max_items=1)
        summaries = memory_list_summaries(max_items=1)
        mood = recent_mood_label()

        bits: list[str] = []
        if reflections:
            recap = reflections[-1]
            if len(recap) > 320:
                recap = recap[:317] + "..."
            bits.append("Yesterday we wrapped up with this: " + recap)
        elif summaries:
            recap = summaries[-1]
            if len(recap) > 320:
                recap = recap[:317] + "..."
            bits.append("Last time we discussed: " + recap)
        if facts:
            bits.append("I remember: " + "; ".join(facts))
        if mood and mood not in ("neutral", "calm"):
            bits.append(f"You've seemed {mood} lately — I'll keep that in mind.")

        try:
            from open_loops import list_open_loops

            loops = list_open_loops(limit=2)
            if loops:
                bits.append(f"Still on your list: {loops[0].text}.")
        except Exception:
            pass

        try:
            from mood_trajectory import mood_trajectory_summary

            traj = mood_trajectory_summary()
            if traj and traj not in bits:
                bits.append(traj)
        except Exception:
            pass

        if bits:
            welcome = "Welcome back" + (f", {address}" if address else "") + ". "
            speak_reply(welcome + " ".join(bits))
        else:
            intro = f"I'm {persona_label}. How can I help"
            speak_reply(intro + (f", {address}?" if address else "?"))
    except Exception:
        speak_reply(
            f"I'm your personal assistant. How can I help"
            + (f", {address}?" if address else "?")
        )

    try:
        from datetime import datetime as _dt

        from reminders import describe_reminder_due, list_pending_reminders

        pending = list_pending_reminders(limit=3)
        if pending:
            phrases = [
                f"{msg} at {describe_reminder_due(_dt.fromtimestamp(due))}"
                for _rid, msg, due, _rec in pending
            ]
            speak_reply("You have upcoming reminders: " + "; ".join(phrases) + ".")
    except Exception:
        pass

# Function to Check if Internet Connection is Available
def connect(host='https://www.google.com/'):
    try:
        urllib.request.urlopen(host)
        return True
    except:
        return False

# Function to Read News
def News():
    # Change the API_KEY to your One

    query_params = {
        "source": "bbc-news",
        "sortBy": "top",
        "apiKey": "YOUR_API_KEY_HERE"
    }
    main_url = " https://newsapi.org/v1/articles"
    res = requests.get(main_url, params=query_params)
    open_bbc_page = res.json()
    article = open_bbc_page["articles"]
    results = []
    for ar in article:
        results.append(ar["title"])
    for i in range(len(results)):
        print(i + 1, results[i])
        speak(results[i])

# Function for Calculations
# def get_operator(op):
#     return{
#         '+': operator.add(),
#         '-': operator.sub(),
#         'x': operator.mul(),
#         'divided': operator.__truediv__(),
#         'mod': operator.mod(),
#         }[op]

def evaluate(op1, operation, op2):
    op1 = int(op1)
    op2 = int(op2)
    if(operation == '+'):
        return op1+op2
    elif(operation == '-'):
        return op1-op2
    elif (operation == 'multiply'):
        return op1*op2
    elif (operation == "divide"):
        if(op2!=0):
            return op1/op2
        else:
            speak("Divide by Zero Error")
            return -1

    # return get_operator(operation)(op1, op2)

# Voice commands often include "Jarvis", "the", etc. — normalize before matching.
_STOPWORDS = {"the", "a", "an"}

SITE_ALIASES = {
    "youtube": "https://www.youtube.com/",
    "google": "https://www.google.com/",
    "gmail": "https://mail.google.com/",
    "github": "https://github.com/",
}


def normalize_voice_query(q: str) -> str:
    if not q or q.strip().lower() == "none":
        return "none"
    q = q.lower().strip()
    for noise in (
        "hey friday", "hey jarvis", "hey", "jarvis", "friday",
        "please", "can you", "okay", "ok",
    ):
        q = q.replace(noise, " ")
    parts = [p for p in q.split() if p not in _STOPWORDS]
    return " ".join(parts)


def wants_site(q: str, site_kw: str) -> bool:
    """Match open youtube / open the youtube / go to youtube / launch youtube."""
    if site_kw not in q:
        return False
    if f"open {site_kw}" in q or f"launch {site_kw}" in q or f"start {site_kw}" in q:
        return True
    if f"go to {site_kw}" in q or f"visit {site_kw}" in q:
        return True
    if f"to {site_kw}" in q and any(x in q for x in ("go", "take me", "take me to")):
        return True
    return False


def try_open_website(query: str) -> bool:
    for site, url in SITE_ALIASES.items():
        if wants_site(query, site):
            speak(f"Opening {site}")
            webbrowser.open(url)
            return True
    return False





def process_command(query: str, voice_raw: Optional[str] = None) -> None:
    """Handle one normalized voice command (must not be 'none').
    ``voice_raw`` is the verbatim (often lower-cased) transcript for episodic memory.
    """
    # 0) Confirmation gate — if a high-risk action is awaiting yes/no, handle it first.
    try:
        from privacy import has_pending, resolve_pending

        if has_pending():
            q_norm = query.strip().lower().rstrip(" .!?,")
            if q_norm in ("yes", "yeah", "yep", "confirm", "do it", "go ahead",
                          "proceed", "approved", "yes please"):
                ran, msg = resolve_pending(True)
                speak(msg)
                return
            if q_norm in ("no", "nope", "cancel", "abort", "stop", "never mind",
                          "nevermind", "don't", "do not"):
                _, msg = resolve_pending(False)
                speak(msg)
                return
            # Otherwise fall through; treat new query normally but warn.
    except Exception:
        pass

    # All Task that Can be Performed by Jarvis

    # 1) Open websites (uses default browser — works on macOS; old code forced broken Windows Chrome path)
    if try_open_website(query):
        pass

    # 1b) Open common apps (cross-platform)
    elif "open notepad" in query or ("notepad" in query and "open" in query):
        speak("Opening text editor")
        if sys.platform == "win32":
            os.startfile("C:\\WINDOWS\\system32\\notepad.exe")
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "TextEdit"], check=False)
        elif shutil.which("gedit"):
            subprocess.run(["gedit"], check=False)
        elif shutil.which("mousepad"):
            subprocess.run(["mousepad"], check=False)

    elif "open command prompt" in query or "open terminal" in query or (
        "terminal" in query and "open" in query
    ):
        speak("Opening terminal")
        if sys.platform == "win32":
            os.system("start cmd")
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Terminal"], check=False)
        else:
            for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "kitty"):
                if shutil.which(term):
                    subprocess.run([term], check=False)
                    break

    elif (
        "open code" in query
        or "open vscode" in query
        or "open vs code" in query
        or "open visual studio code" in query
    ):
        speak("Opening Visual Studio Code")
        if sys.platform == "win32":
            code_path = os.path.expanduser(
                r"~\AppData\Local\Programs\Microsoft VS Code\Code.exe"
            )
            if os.path.isfile(code_path):
                os.startfile(code_path)
            else:
                os.startfile("code")
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Visual Studio Code"], check=False)
        elif shutil.which("code"):
            subprocess.run(["code"], check=False)

    # 2) Play Any Random Music or Particular Music
    elif 'play' in query:
        song = query.replace('jarvis', '')
        song = song.replace('play', '')
        txt = "playing" + song
        speak(txt)
        pywhatkit.playonyt(song)

    # 3) Increase/decrease the speakers master volume
    elif 'volume up' in query:
        pyautogui.press("volumeup")
    elif 'volume down' in query:
        pyautogui.press("volumedown")
    elif 'volume mute' in query or 'mute' in query:
        pyautogui.press("volumemute")

    # 4) Opens any System App [For Eg: Calculator]
    elif "open calculator" in query or ("calculator" in query and "open" in query):
        speak("Opening calculator")
        if sys.platform == "win32":
            call(["calc.exe"])
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Calculator"], check=False)
        elif shutil.which("gnome-calculator"):
            subprocess.run(["gnome-calculator"], check=False)

    elif query.startswith("open ") or query.startswith("launch ") or query.startswith("start "):
        for prefix in ("open ", "launch ", "start "):
            if query.startswith(prefix):
                app_name = query[len(prefix):].strip(" .")
                break
        else:
            app_name = ""
        if app_name and app_name not in ("the", "a", "an"):
            if sys.platform == "darwin":
                opened = False
                for candidate in (app_name, app_name.title(), app_name.capitalize()):
                    res = subprocess.run(
                        ["open", "-a", candidate],
                        capture_output=True,
                        text=True,
                    )
                    if res.returncode == 0:
                        speak(f"Opening {candidate}")
                        opened = True
                        break
                if not opened:
                    speak(f"I couldn't open {app_name}. Check the app name in Applications.")
            else:
                import jarvis_actions as ja

                speak(ja.open_application(app_name))

    # 5) Tells about something, by searching on the internet
    elif (
        "search google" in query
        or "google search" in query
        or "search on google" in query
    ):
        speak("Sir, What should I search on Google?")
        cm = take_command().lower()
        cm = normalize_voice_query(cm)
        if cm and cm != "none":
            webbrowser.open(f"https://www.google.com/search?q={quote_plus(cm)}")

    elif 'who is' in query:
        name = query.replace('jarvis', '')
        name = name.replace('who is', '')
        info = wikipedia.summary(name)
        print(info)
        speak(info)

    elif 'wikipedia' in query:
        speak('searching wikipedia...')
        to_search = query.replace('jarvis', '')
        to_search = to_search.replace('wikipedia', '')
        results = wikipedia.summary(to_search, sentences=2)
        speak('According to Wikipedia, ')
        speak(results)

    elif wants_learn_knowledge(query):
        if not _RAG_AVAILABLE:
            speak(
                "Sir, knowledge mode needs extra packages: pip install -r requirements-rag.txt."
            )
        else:
            note = extract_learn_text(query)
            if len(note.strip()) < 8:
                speak("What fact should I add to your knowledge base?")
                follow = normalize_voice_query(take_command().lower())
                if follow == "none":
                    return
                note = follow
            from knowledge.note_writer import save_voice_note
            from knowledge.rag_store import sync_knowledge_folder

            msg = save_voice_note(note)
            try:
                indexed = sync_knowledge_folder()
                if indexed:
                    msg += f" Indexed {indexed} chunks."
            except Exception:
                traceback.print_exc()
            speak(msg)

    elif (
        query.startswith("remind me ")
        or query.startswith("set a reminder")
        or query.startswith("set reminder")
    ):
        from dialogue_state import get_pending_task
        from dialogue_tasks import (
            maybe_open_incomplete_command,
            try_finish_reminder,
        )

        utterance = voice_raw or query
        result = try_finish_reminder(utterance)
        if result:
            speak_reply(result)
        elif maybe_open_incomplete_command(query, utterance):
            task = get_pending_task()
            speak_reply((task or {}).get("prompt") or "What should I remind you about?")
        else:
            speak_reply(
                "I could not understand the time. Try 'remind me to call mom in 10 minutes', "
                "'remind me to take pills at 9pm', or 'remind me to stretch every weekday at 3pm'."
            )

    elif (
        "list reminders" in query
        or "show reminders" in query
        or "what are my reminders" in query
        or "my reminders" in query
    ):
        from datetime import datetime as _dt

        from reminders import describe_reminder_due, list_pending_reminders

        items = list_pending_reminders(limit=10)
        if not items:
            speak("You have no pending reminders, Sir.")
        else:
            phrases = []
            for rid, msg, due, recurrence in items:
                tag = f" (recurring {recurrence})" if recurrence else ""
                phrases.append(
                    f"#{rid} at {describe_reminder_due(_dt.fromtimestamp(due))}{tag}: {msg}"
                )
            speak("Pending reminders: " + " | ".join(phrases))

    elif query.startswith("cancel reminder"):
        from reminders import cancel_reminder

        m = re.search(r"\bcancel reminder\s+#?(\d+)\b", query)
        if not m:
            speak("Please say 'cancel reminder' followed by the reminder number.")
        else:
            rid = int(m.group(1))
            ok = cancel_reminder(rid)
            speak(f"Cancelled reminder {rid}." if ok else f"No pending reminder {rid} to cancel.")

    elif (
        "what's on my screen" in query
        or "what is on my screen" in query
        or "describe my screen" in query
        or "describe the screen" in query
        or "look at my screen" in query
        or "see my screen" in query
    ):
        from vision import describe_screen

        speak_filler()
        speak(describe_screen())

    elif query.startswith("describe screen "):
        from vision import describe_screen

        prompt = query[len("describe screen ") :].strip()
        speak_filler()
        speak(describe_screen(prompt=prompt))

    elif _vision_url_command(query):
        from vision import analyze_target

        url, prompt = _parse_vision_url_command(query)
        if not url:
            speak("Please give me an http or https URL after 'look at'.")
        else:
            speak_filler()
            speak(analyze_target(url, prompt=prompt))

    elif _vision_compare_command(query):
        from vision import analyze_images, image_history

        prompt = _extract_vision_prompt(query, _COMPARE_TRIGGERS)
        hist = image_history()
        if len(hist) < 2:
            speak("I need at least two recent images to compare, Sir.")
        else:
            paths = [hist[-2]["path"], hist[-1]["path"]]
            speak_filler()
            res = analyze_images(paths, prompt=prompt, mode="compare")
            speak(res.get("text") or "I could not compare those images, Sir.")

    elif _vision_read_text_command(query):
        from vision import (
            extract_text_from_image,
            take_screenshot,
            get_last_image,
            capture_clipboard_image,
            capture_webcam,
        )

        target = _vision_read_text_target(query)
        speak_filler()
        if target == "screen":
            ok, info = take_screenshot()
        elif target == "clipboard":
            ok, info = capture_clipboard_image()
        elif target == "camera":
            ok, info = capture_webcam()
        else:
            path, _ = get_last_image()
            ok, info = (bool(path), path or "I don't have a recent image to read, Sir.")
        if not ok:
            speak(info)
        else:
            data = extract_text_from_image(info)
            text = (data.get("text") or "").strip()
            speak(text if text else "I could not find any readable text, Sir.")

    elif _vision_objects_command(query):
        from vision import detect_objects, get_last_image, take_screenshot, capture_webcam

        target = _vision_objects_target(query)
        speak_filler()
        if target == "screen":
            ok, info = take_screenshot()
        elif target == "camera":
            ok, info = capture_webcam()
        else:
            path, _ = get_last_image()
            ok, info = (bool(path), path or "I don't have an image to scan, Sir.")
        if not ok:
            speak(info)
        else:
            result = detect_objects(info)
            objs = result.get("objects") or []
            if not objs:
                speak("I did not spot any salient objects, Sir.")
            else:
                names = ", ".join(str(o.get("label", "?")) for o in objs[:8])
                speak(f"I see {len(objs)} object{'s' if len(objs) != 1 else ''}: {names}.")

    elif _vision_motion_command(query):
        from vision import describe_webcam_motion

        prompt = _extract_vision_prompt(query, _MOTION_TRIGGERS)
        seconds = _vision_motion_seconds(query)
        frames = max(2, min(8, int(round(seconds / 0.6))))
        speak_filler()
        speak(describe_webcam_motion(prompt, frames=frames, interval_s=0.6))

    elif _vision_pdf_command(query):
        from vision import analyze_pdf

        path, prompt = _parse_vision_pdf_command(query)
        if not path:
            speak("Tell me the PDF path after 'analyze pdf'.")
        else:
            speak_filler()
            speak(analyze_pdf(path, prompt=prompt))

    elif _vision_recent_download_command(query):
        from vision import find_recent_image, analyze_image

        prompt = _extract_vision_prompt(query, _RECENT_DOWNLOAD_TRIGGERS)
        recent = find_recent_image()
        if not recent:
            speak("I could not find a recent image in your Downloads or Desktop, Sir.")
        else:
            speak_filler()
            res = analyze_image(recent, prompt=prompt, history_kind="download")
            speak(res.get("text") or "I could not analyze that image, Sir.")

    elif _vision_generate_command(query):
        from vision import generate_image

        gen_prompt = _parse_vision_generate_command(query)
        if not gen_prompt:
            speak("Tell me what to generate, Sir — for example, 'generate an image of a red sports car at sunset'.")
        else:
            speak_filler()
            result = generate_image(gen_prompt)
            if result.get("ok"):
                speak(f"Image generated and saved to {result.get('path')}, Sir.")
            else:
                speak(result.get("error") or "I could not generate that image, Sir.")

    elif _vision_webcam_command(query):
        from vision import describe_webcam

        prompt = _extract_vision_prompt(query, _WEBCAM_TRIGGERS)
        speak_filler()
        speak(describe_webcam(prompt=prompt))

    elif _vision_clipboard_command(query):
        from vision import describe_clipboard_image

        prompt = _extract_vision_prompt(query, _CLIPBOARD_TRIGGERS)
        speak_filler()
        speak(describe_clipboard_image(prompt=prompt))

    elif _vision_image_file_command(query):
        from vision import describe_image

        path, prompt = _parse_image_file_command(query)
        if not path:
            speak("Please say something like: describe image followed by the file path.")
        else:
            speak_filler()
            speak(describe_image(path, prompt=prompt))

    elif _vision_followup_command(query):
        from vision import ask_about_last_image
        from vision_session import is_active, session_ask

        prompt = _extract_vision_prompt(query, _FOLLOWUP_TRIGGERS)
        speak_filler()
        if is_active():
            speak_reply(session_ask(prompt))
        else:
            speak_reply(ask_about_last_image(prompt))

    elif query in (
        "start vision session",
        "look at this with me",
        "stay on this image",
        "vision session on",
    ):
        from vision_session import start_vision_session

        speak_reply(start_vision_session())

    elif query in ("end vision session", "stop vision session", "done with this image"):
        from vision_session import end_vision_session

        speak_reply(end_vision_session())

    elif query in ("vision session status", "is vision session on"):
        from vision_session import describe_session

        speak_reply(describe_session())

    elif query in ("weekly digest", "week in review", "how was my week", "summarize my week"):
        from weekly_digest import speak_weekly_digest

        speak_filler()
        speak_weekly_digest(speak_reply)

    elif query in ("open loops", "what's still open", "whats still open", "pending commitments"):
        from open_loops import describe_for_voice

        speak_reply(describe_for_voice())

    elif query.startswith("done with loop ") or query.startswith("resolve loop "):
        from open_loops import resolve_loop

        m = re.search(r"#?(\d+)\s*$", query)
        if not m:
            speak_reply("Say 'resolve loop' followed by the number.")
        else:
            ok = resolve_loop(int(m.group(1)))
            speak_reply("Marked done." if ok else "I couldn't find that loop.")

    elif query.startswith("draft a message ") or query.startswith("draft message "):
        from message_draft import draft_message

        for prefix in ("draft a message ", "draft message "):
            if query.startswith(prefix):
                intent = query[len(prefix):].strip()
                break
        else:
            intent = query
        speak_reply(draft_message(intent))

    elif "running late" in query or "i'm late" in query or "i am late" in query:
        from message_draft import handle_running_late, parse_running_late

        parsed = parse_running_late(voice_raw or query)
        if parsed:
            mins, recipient = parsed
            speak_reply(handle_running_late(mins, recipient_hint=recipient))
        else:
            speak_reply(handle_running_late(5))

    elif query in ("start glance mode", "enable glance mode", "watch my screen"):
        from glance_mode import start_glance_mode

        if start_glance_mode(speak_reply):
            speak_reply("Glance mode on — I'll check your screen periodically during work.")
        else:
            speak_reply("Set JARVIS_GLANCE_MODE=1 in your env, then try again.")

    elif query in ("stop glance mode", "disable glance mode"):
        from glance_mode import stop_glance_mode

        stop_glance_mode()
        speak_reply("Glance mode off.")

    elif query in ("remember my face", "enroll my face", "learn my face"):
        from identity_fusion import enroll_active_user_face

        speak_reply(enroll_active_user_face())

    elif query in ("companion status", "phone api status"):
        from companion_bridge import enabled as companion_on, is_running as companion_running

        if not companion_on():
            speak_reply("Companion API is off. Set JARVIS_COMPANION=1.")
        elif companion_running():
            port = os.environ.get("JARVIS_COMPANION_PORT", "8765")
            speak_reply(f"Companion API is running on port {port}.")
        else:
            speak_reply("Companion API is enabled but not running.")

    elif query in ("local brain status", "ollama status", "is local llm on"):
        try:
            from local_llm import local_llm_mode, ollama_available, ollama_model

            if ollama_available():
                speak_reply(f"Local brain ready — Ollama model {ollama_model()}, mode {local_llm_mode()}.")
            else:
                speak_reply(f"Ollama not reachable. Mode is {local_llm_mode()}.")
        except Exception:
            speak_reply("Local LLM module unavailable.")

    elif query in ("wake listener status", "always on wake status"):
        try:
            from porcupine_wake import describe_status as porc_status, enabled as porc_on
            from wake_listener import enabled as wake_on, is_running as wake_running

            if porc_on():
                speak_reply(porc_status())
            elif wake_on() and wake_running():
                speak_reply("Always-on wake listener is active (Whisper/VAD).")
            elif wake_on():
                speak_reply("Wake listener is enabled but not running.")
            else:
                speak_reply("Always-on wake is off. Set JARVIS_ALWAYS_ON_WAKE=1 or auto.")
        except Exception:
            speak_reply("Wake listener unavailable.")

    elif query in ("mic status", "microphone status", "list microphones", "list mics"):
        try:
            from mic_profile import describe_mic_profile, list_input_devices

            devices = list_input_devices()
            if not devices:
                speak_reply(describe_mic_profile() + " No input devices found.")
            else:
                names = [f"{d['index']}: {d['name'][:40]}" for d in devices[:6]]
                speak_reply(describe_mic_profile() + " Devices: " + "; ".join(names))
        except Exception:
            speak_reply("Mic profile unavailable.")

    elif query.startswith("map scene ") or query.startswith("map shortcut "):
        from smart_home import save_scene_alias

        body = query.split(" ", 2)
        if len(body) < 3 or " to " not in query:
            speak_reply("Say map scene followed by the spoken phrase, then 'to', then the shortcut name.")
        else:
            left, _, shortcut = query.partition(" to ")
            spoken = left.split(" ", 2)[-1].strip()
            speak_reply(save_scene_alias(spoken, shortcut.strip()))

    elif query in ("do not disturb", "don't disturb me", "do not disturb me",
                   "be quiet", "stay quiet", "quiet mode on"):
        from ambient import set_dnd

        set_dnd(True)
        speak_reply("Quiet mode on. I'll only interrupt for the essentials.")

    elif query in ("you can talk again", "resume notifications", "quiet mode off",
                   "back to normal", "you can interrupt me"):
        from ambient import set_dnd

        set_dnd(False)
        speak_reply("Back to normal.")

    elif (
        "leave me alone" in query
        or "not now" in query
        or query.startswith("snooze ambient")
        or query.startswith("snooze check")
        or "stop nudging" in query
        or "quiet for" in query
        or query.startswith("dnd for")
    ):
        from ambient import parse_snooze_command, snooze

        parsed = parse_snooze_command(voice_raw or query)
        if parsed:
            category, seconds = parsed
            snooze(category, seconds)
            mins = max(1, int(round(seconds / 60)))
            speak_reply(f"Got it — I'll stay quiet for about {mins} minute{'s' if mins != 1 else ''}.")
        else:
            snooze("all", 3600.0)
            speak_reply("Okay — I'll check in again in about an hour.")

    elif query in ("pause ambient", "stop checking in", "pause check ins",
                   "pause check-ins"):
        from ambient import set_paused

        set_paused(True)
        speak("Ambient checks paused.")

    elif query in ("resume ambient", "resume check ins", "resume check-ins",
                   "start checking in"):
        from ambient import set_paused

        set_paused(False)
        speak("Ambient checks resumed.")

    elif query in ("ambient status", "are you watching", "what are you watching"):
        from ambient import describe_status

        speak(describe_status())

    elif query in ("what app am i in", "what window am i on", "what am i looking at right now",
                   "what's in front of me"):
        from awareness import active_app

        info = active_app()
        if not info:
            speak("I can't see your active window, Sir.")
        else:
            title = info.get("window_title") or ""
            if title:
                speak(f"You're in {info['name']}, window: {title[:80]}.")
            else:
                speak(f"You're in {info['name']}.")

    elif query in ("describe my environment", "where am i", "what's going on around me",
                   "give me situational awareness", "what's my context"):
        from awareness import describe_environment

        speak(describe_environment())

    elif query in ("what's my focus mode", "am i in focus mode", "what focus mode am i in"):
        from awareness import focus_mode

        m = focus_mode()
        speak(f"Focus mode: {m}." if m else "No Focus mode is active, Sir.")

    elif query in ("listen for sounds", "watch for sounds", "monitor sounds", "monitor for sounds"):
        if not _start_sound_monitor():
            speak("Sound monitor unavailable — install sounddevice or pyaudio.")
        else:
            speak("Listening for ambient sounds, Sir.")

    elif query in ("stop listening for sounds", "stop monitoring sounds"):
        if _stop_sound_monitor():
            speak("Sound monitor stopped.")
        else:
            speak("The sound monitor wasn't running.")

    elif query in ("daily reflection", "reflect on today", "what did we do today",
                   "summarize today", "summarise today", "end of day reflection"):
        from reflection import speak_reflection

        speak_filler()
        speak_reflection(speak)

    elif query in ("list threads", "what are we working on", "show open threads",
                   "what topics are open"):
        from topic_threads import describe_threads_for_voice

        speak(describe_threads_for_voice())

    elif query.startswith("resolve thread "):
        from topic_threads import resolve_thread

        label = query[len("resolve thread "):].strip()
        t = resolve_thread(label) if label else None
        speak(f"Marked '{t.label}' as resolved, Sir." if t
              else f"I couldn't find an open thread matching '{label}'.")

    elif query.startswith("forget thread "):
        from topic_threads import forget_thread

        label = query[len("forget thread "):].strip()
        speak("Thread forgotten, Sir." if forget_thread(label)
              else f"No thread matching '{label}'.")

    elif query in ("list personas", "what personas are available", "show personas"):
        from personas import list_personas

        items = list_personas()
        speak("Available personas: " + ", ".join(f"{p['key']} ({p['label']})" for p in items) + ".")

    elif _persona_switch_command(query):
        from personas import set_persona_key, describe_current_persona

        key = _persona_switch_target(query)
        if not key or not set_persona_key(key):
            speak("I don't recognize that persona. Try jarvis, friday, companion, coach, or therapist.")
        else:
            speak(describe_current_persona())

    elif query in ("current persona", "what persona", "who are you right now",
                   "what mode are you in"):
        from personas import describe_current_persona

        speak(describe_current_persona())

    elif query in ("be brief", "be terse", "shorter please", "give me short answers",
                   "keep it short"):
        from personas import set_verbosity

        set_verbosity("terse")
        speak("Short answers it is.")

    elif query in ("be normal", "normal verbosity", "default verbosity",
                   "okay normal length"):
        from personas import set_verbosity

        set_verbosity("normal")
        speak("Back to normal length.")

    elif query in ("be verbose", "more detail", "tell me more", "be thorough",
                   "longer answers please", "expand on that"):
        from personas import set_verbosity

        set_verbosity("rich")
        speak("I'll go deeper, then.")

    elif query.startswith("call me "):
        from personas import set_address

        new_name = query[len("call me "):].strip(" .,!?")
        if not new_name:
            speak("By what should I call you?")
        else:
            set_address(new_name)
            speak(f"Okay — I'll call you {new_name} from now on.")

    elif query in ("no honorific", "drop the sir", "don't call me sir",
                   "stop calling me sir"):
        from personas import set_address

        set_address("")
        speak("Got it — no honorific.")

    elif query in ("private mode on", "go private", "enter private mode",
                   "start private mode", "this is private", "off the record"):
        from privacy import set_private

        set_private(True)
        speak("Private mode on. Nothing will be logged this session.")

    elif query in ("private mode off", "exit private mode", "stop private mode",
                   "back on the record"):
        from privacy import disable_private_and_purge

        result = disable_private_and_purge()
        n = result.get("episodic_deleted", 0) + result.get("actions_deleted", 0)
        speak(f"Private mode off. Purged {n} record{'s' if n != 1 else ''} from this session.")

    elif query in ("privacy status", "am i private", "what's my privacy",
                   "what's the privacy state"):
        from privacy import describe_privacy_state

        speak(describe_privacy_state())

    elif query.startswith("forget the last "):
        from privacy import forget_recent_minutes

        m = re.search(r"forget the last (\d+)\s*(minute|minutes|min|mins|m)\b", query)
        if not m:
            speak("Say 'forget the last 5 minutes' (or similar).")
        else:
            mins = int(m.group(1))
            result = forget_recent_minutes(mins)
            n = result.get("episodic_deleted", 0) + result.get("actions_deleted", 0)
            speak(f"Purged {n} record{'s' if n != 1 else ''} from the last {mins} minute(s).")

    elif query in ("forget today", "wipe today", "forget everything from today"):
        from privacy import forget_today

        result = forget_today()
        n = result.get("episodic_deleted", 0) + result.get("actions_deleted", 0)
        speak(f"Purged {n} record{'s' if n != 1 else ''} from today.")

    elif query in ("watch the camera", "start live camera", "live camera on",
                   "keep an eye on me"):
        if _start_live_camera():
            speak("Live camera observer running. I'll only speak up if I notice something useful.")
        else:
            speak("Couldn't start the live camera observer.")

    elif query in ("stop watching the camera", "stop live camera", "live camera off"):
        speak("Live camera observer stopped." if _stop_live_camera()
              else "Live camera wasn't running.")

    elif query in ("watch the screen", "start live screen", "live screen on",
                   "keep an eye on my screen"):
        if _start_live_screen():
            speak("Live screen observer running. I'll only speak up for errors or stuck states.")
        else:
            speak("Couldn't start the live screen observer.")

    elif query in ("stop watching the screen", "stop live screen", "live screen off"):
        speak("Live screen observer stopped." if _stop_live_screen()
              else "Live screen wasn't running.")

    elif query in ("voice settings", "what voice are you using right now",
                   "describe voice", "current voice settings"):
        try:
            from voice_emotion import describe_voice_state

            speak(describe_voice_state())
        except Exception:
            speak("Voice settings unavailable.")

    elif query in ("reset voiceprint", "forget my voice", "forget my voiceprint"):
        try:
            from speaker_id import reset_voiceprint

            reset_voiceprint()
            speak("Voiceprint reset. I'll re-learn your voice over the next few utterances.")
        except Exception:
            speak("Voiceprint reset failed.")

    elif query in ("undo", "undo last", "undo that"):
        from action_history import undo_last

        speak(undo_last())

    elif query.startswith("undo last "):
        from action_history import undo_last

        kind = query[len("undo last ") :].strip()
        speak(undo_last(kind=kind))

    elif query in ("recent actions", "show recent actions", "action history"):
        from action_history import describe_recent_actions

        speak(describe_recent_actions())

    elif _user_voice_command(query):
        from user_profiles import (
            describe_active_user,
            list_users,
            parse_user_command,
            set_active_user,
        )

        intent, value = parse_user_command(query)
        if intent == "switch":
            uid = set_active_user(value, display_name=value)
            speak(f"Switched to user {uid}, Sir.")
        elif intent == "who":
            speak(describe_active_user())
        elif intent == "list":
            users = list_users()
            if not users:
                speak("Only the default user has been seen, Sir.")
            else:
                names = ", ".join(u.get("display_name") or u["user_id"] for u in users)
                speak("Known users: " + names)

    elif (
        "daily briefing" in query
        or "morning briefing" in query
        or "brief me" in query
        or "give me a briefing" in query
        or "what's on today" in query
        or "what is on today" in query
    ):
        from briefing import build_daily_briefing

        speak_filler()
        speak(build_daily_briefing())

    elif (
        query.startswith("email myself ")
        or query.startswith("email me ")
        or query.startswith("send myself ")
    ):
        from dialogue_state import get_pending_task
        from dialogue_tasks import maybe_open_incomplete_command
        from outgoing import email_myself

        for prefix in ("email myself ", "email me ", "send myself "):
            if query.startswith(prefix):
                body = query[len(prefix) :].strip()
                break
        else:
            body = ""
        if not body:
            if maybe_open_incomplete_command(query, voice_raw or query):
                task = get_pending_task()
                speak_reply((task or {}).get("prompt") or "What should I email you?")
            else:
                speak_reply("What should I email you?")
        else:
            result = email_myself(body, subject="Note from Jarvis")
            speak_reply(result)

    elif (
        query.startswith("slack ")
        or query.startswith("send slack ")
        or query.startswith("post to slack ")
    ):
        from outgoing import slack_post

        for prefix in ("post to slack ", "send slack ", "slack "):
            if query.startswith(prefix):
                text = query[len(prefix) :].strip()
                break
        if not text:
            speak("What should I post to Slack, Sir?")
            follow = normalize_voice_query(take_command().lower())
            if follow == "none":
                return
            text = follow
        result = slack_post(text)
        speak(result)

    elif (
        "sync now" in query
        or "sync memory" in query
        or "sync state" in query
        or "run sync" in query
    ):
        from sync_service import sync_now

        speak(sync_now())

    elif "sync status" in query:
        from sync_service import describe_sync_status

        speak(describe_sync_status())

    elif (
        "today's calendar" in query
        or "my calendar today" in query
        or "calendar today" in query
        or query.startswith("what's on my calendar")
        or query.startswith("what is on my calendar")
    ):
        from calendar_service import calendar_available, calendar_today_events

        if not calendar_available():
            speak("Calendar is only available on macOS at the moment, Sir.")
        else:
            items = calendar_today_events(limit=6)
            if not items:
                speak("Your calendar is clear today, Sir.")
            else:
                phrases = [
                    f"{it['title']} from {it['start']} to {it['end']}"
                    for it in items
                ]
                speak("Today's events: " + "; ".join(phrases))

    elif (
        "upcoming calendar" in query
        or "calendar upcoming" in query
        or "next on my calendar" in query
        or "what's next on my calendar" in query
    ):
        from calendar_service import calendar_available, calendar_upcoming_events

        if not calendar_available():
            speak("Calendar is only available on macOS at the moment, Sir.")
        else:
            items = calendar_upcoming_events(hours=48, limit=6)
            if not items:
                speak("Nothing scheduled in the next 48 hours, Sir.")
            else:
                phrases = [f"{it['title']} at {it['start']}" for it in items]
                speak("Upcoming events: " + "; ".join(phrases))

    elif (
        query.startswith("schedule ")
        or query.startswith("add to calendar ")
        or query.startswith("add calendar event ")
        or query.startswith("create event ")
        or query.startswith("create calendar event ")
        or query.startswith("new event ")
        or query.startswith("put on my calendar ")
    ):
        from calendar_service import calendar_available
        from dialogue_state import get_pending_task
        from dialogue_tasks import maybe_open_incomplete_command, try_finish_calendar

        if not calendar_available():
            speak_reply("Calendar is only available on macOS at the moment.")
        else:
            utterance = voice_raw or query
            result = try_finish_calendar(utterance)
            if result:
                speak_reply(result)
            elif maybe_open_incomplete_command(query, utterance):
                task = get_pending_task()
                speak_reply((task or {}).get("prompt") or "What should I call this event?")
            else:
                speak_reply(
                    "I could not parse a time. Try 'schedule lunch tomorrow at 12:30 for 1 hour'."
                )

    elif (
        query.startswith("ask everything ")
        or query.startswith("deep dive ")
        or query.startswith("comprehensive answer ")
        or query.startswith("research ")
    ):
        topic = ""
        for prefix in (
            "ask everything ",
            "deep dive ",
            "comprehensive answer ",
            "research ",
        ):
            if query.startswith(prefix):
                topic = query[len(prefix) :].strip(" .,!?:;")
                break
        if not topic:
            speak("What should I research, Sir?")
            follow = normalize_voice_query(take_command().lower())
            if follow == "none":
                return
            topic = follow
        from unified_ask import unified_ask

        speak_filler()
        result = unified_ask(topic)
        speak(result.get("reply") or "I formed no spoken answer, Sir.")

    elif (
        "summarize memory" in query
        or "compress memory" in query
        or "summarise memory" in query
    ):
        from memory.episodic_memory import maybe_summarize_old_turns

        stored = maybe_summarize_old_turns(force=True)
        if stored:
            speak("Done, Sir. I compressed older turns into a long-term memory summary.")
        else:
            speak("Not enough conversation history yet to summarize meaningfully.")

    elif (
        "search the web" in query
        or "search web for" in query
        or query.startswith("web search ")
        or query.startswith("search web ")
    ):
        from web_search import format_results_for_voice, search_web

        for prefix in (
            "search the web for ",
            "search web for ",
            "web search ",
            "search web ",
            "search the web ",
        ):
            if prefix in query:
                topic = query.split(prefix, 1)[-1].strip(" .,!?:;")
                break
        else:
            topic = ""
        if not topic:
            speak("What should I search the web for, Sir?")
            follow = normalize_voice_query(take_command().lower())
            if follow == "none":
                return
            topic = follow
        results = search_web(topic, limit=5)
        speak(format_results_for_voice(results))

    elif "knowledge status" in query or "knowledge base status" in query:
        if not _RAG_AVAILABLE:
            speak("Knowledge mode is not installed yet. Run pip install -r requirements-rag.txt.")
        else:
            from knowledge.rag_store import describe_knowledge_for_voice

            speak(describe_knowledge_for_voice())

    elif (
        "resync knowledge" in query
        or "refresh knowledge" in query
        or "reindex knowledge" in query
    ):
        if not _RAG_AVAILABLE:
            speak("Knowledge mode is not installed yet. Run pip install -r requirements-rag.txt.")
        else:
            from knowledge.rag_store import force_resync_knowledge

            indexed = force_resync_knowledge()
            speak(f"Knowledge reindexed, Sir. Embedded {indexed} chunks.")

    elif "ingest url" in query or "save url" in query or "learn url" in query:
        if not _RAG_AVAILABLE:
            speak("Knowledge mode is not installed yet. Run pip install -r requirements-rag.txt.")
        else:
            from knowledge.rag_store import sync_knowledge_folder
            from knowledge.url_ingest import ingest_url_into_knowledge

            url = extract_url(query) or extract_url(voice_raw or "")
            if not url:
                speak("Please say the URL to ingest.")
                follow = take_command().lower()
                url = extract_url(follow)
            if not url:
                speak("I did not catch a valid URL, Sir.")
                return
            msg = ingest_url_into_knowledge(url)
            try:
                indexed = sync_knowledge_folder()
                if indexed:
                    msg += f" Indexed {indexed} chunks."
            except Exception:
                traceback.print_exc()
            speak(msg)

    elif wants_knowledge_lookup(query):
        if not _RAG_AVAILABLE:
            speak(
                "Sir, knowledge mode needs extra packages: pip install -r requirements-rag.txt."
            )
        else:
            qtopic = extract_kb_question(query)
            if len(qtopic.strip()) < 4:
                speak("What topic should I search in your knowledge documents, Sir?")
                follow = normalize_voice_query(take_command().lower())
                if follow == "none":
                    return
                qtopic = follow
            speak_filler()
            try:
                reply = answer_from_knowledge(qtopic)
            except Exception as exc:
                traceback.print_exc()
                reply = f"Sir, knowledge lookup failed: {exc}"
            speak(reply)

    #6) Tells the weather for a place
    elif 'weather' in query:
        api_key = "YOUR_WEATHER_API_KEY_HERE"
        base_url = "http://api.openweathermap.org/data/2.5/weather?"
        speak("Sir, For Which Place you want to know the Weather?")
        place = take_command().lower()
        complete_url = base_url + "appid=" + api_key + "&q=" + place
        response = requests.get(complete_url)
        x = response.json()
        if response.status_code == 200:
            y = x['main']
            current_temperature = y['temp']
            z = x['weather']
            weather_description = z[0]['description']
            t3 = "Temperature at " + place + " is " + str(current_temperature) + " Kelvin and Climate is " + str(weather_description)
            print(t3)
            speak(t3)
        else:
            speak("City Not Found Sir")

    #7) Tells the current time and/or date
    elif 'time' in query:
        time_str = datetime.datetime.now().strftime('%I:%M %p')
        t1 = "Current Time is " + time_str
        speak(t1)
    elif 'date' in query:
        from datetime import date
        today = date.today()
        d2 = today.strftime("%B %d, %Y")
        t2 = "Today is " + d2
        print(t2)
        speak(t2)

    #8) Set an Alarm
    elif 'alarm' in query:
        speak("Sir, Please tell me the time to set the alarm, Example - set alarm for 6:30 am")
        res = take_command().lower()
        res = res.replace('set alarm for', '')
        res = res.replace('.', '')
        res = res.upper()
        print(res)
        import MyAlarm
        MyAlarm.alarm(res)

    #9) Tell the Internet Speed
    elif 'internet speed' in query:
        st = speedtest.Speedtest()
        download_speed = str(round(float(st.download()/1000000)))
        upload_speed = str(round(float(st.upload()/1000000)))
        t5 = f"Sir, You Internet Connection has {download_speed} mega byte per seconds Downloading Speed and {upload_speed} mega byte per second Uploading Speed."
        print(t5)
        speak(t5)

    #10) Internet Connection
    elif 'internet connection' in query:
        if connect()==True:
            msg1 = "Internet Connection Available Sir"
            print(msg1)
            speak(msg1)
        else:
            msg2 = "Internet Connection Not Available Sir"
            print(msg2)
            speak(msg2)

    #11) Tell the Daily News
    elif 'news' in query:
        News()

    #12) Spell a Particular Word
    elif 'spell' in query:
        speak("Sir, Please tell me the word to Spell")
        res = take_command().lower()
        for i in res:
            speak(i)

    # Memory management (profile + summary + forgetting)
    elif "what do you remember" in query or "memory summary" in query or "show memory" in query or "list memory" in query:
        from memory.episodic_memory import memory_build_user_memory_summary

        speak(memory_build_user_memory_summary())

    elif "profile" in query and ("show" in query or "list" in query):
        from memory.episodic_memory import memory_list_profile_facts

        facts = memory_list_profile_facts()
        if facts:
            speak("Saved profile facts: " + "; ".join(facts))
        else:
            speak("I don't have any saved profile facts yet, Sir.")

    elif query.startswith("forget "):
        global _pending_forget
        target = query[len("forget ") :].strip()
        if not target:
            speak("Sir, what should I forget?")
        elif target in ("profile", "my profile"):
            _pending_forget = {"kind": "profile"}
            speak("Boss, I can clear your saved profile facts. Confirm by saying 'yes' or say 'cancel'.")
        else:
            _pending_forget = {"kind": "notes", "text": target}
            speak(
                f"Boss, I will remove saved memories matching '{target}'. "
                "Confirm by saying 'yes' or say 'cancel'."
            )

    #13) How much Memory Consumed
    elif 'memory' in query:
        process = psutil.Process(os.getpid())
        msg3 = "Memory Consumed by your computer is " + str(process.memory_info()[0]/1000000) + " Mega bytes"
        print(msg3)
        speak(msg3)

    #14) Calculate
    elif 'calculate' in query:
        speak("What do you want to calculate? Example : 5 plus 10")
        res = take_command().lower()
        msg6 = evaluate(*(res.split(" ")))
        t7 = "Your Result is " + str(msg6)
        print(t7)
        speak(t7)

    # 15) help
    elif 'help' in query:
        speak(
            'I can open apps, play music, search the web, tell time and weather, '
            'manage your memory profile, and answer from your local knowledge base. '
            'Try: knowledge status, resync knowledge, learn that ..., ingest url ..., '
            'search the web for ..., remind me to ... in 10 minutes, remind me to stretch every weekday at 3pm, '
            'list reminders, schedule lunch tomorrow at 12:30 for 1 hour, calendar today, '
            'deep dive on a topic, summarize memory, show profile, ask my documents about a topic, '
            'daily briefing, email myself ..., slack ..., sync now, or sync status. '
            'You can also undo, undo last reminder, list users, switch user to ..., or just say "I am ..." to switch profile. '
            'Newest: what is on my screen, describe the screen, do that again, cancel it, send that to slack.'
        )

    #16) Jokes
    elif 'joke' in query or 'jokes' in query:
        msg9 = pyjokes.get_joke()
        print(msg9)
        speak(msg9)

    #17) Author
    elif "who made you" in query or "who created you" in query:
        speak("I have been created by Bhagya Rana.")

    # 18) exit
    elif 'exit' in query:
        speak("Thanks for giving me your precious time Sir")
        raise JarvisExitRequest

    else:
        if jb is not None and jb.is_brain_enabled():
            from dialogue_state import describe_state_for_prompt, remember_last_topic
            from memory.episodic_memory import (
                memory_auto_capture_user_profile,
                memory_build_context_for_prompt,
            )
            from sentiment import persona_mood_overlay, recent_mood_label

            utterance = voice_raw.strip() if voice_raw else query
            try:
                memory_auto_capture_user_profile(utterance)
                episodic_prefill = memory_build_context_for_prompt(query=utterance)
                ds = describe_state_for_prompt()
                if ds:
                    episodic_prefill = f"Dialogue state:\n{ds}\n\n{episodic_prefill}"
                mood_overlay = persona_mood_overlay(recent_mood_label())
                if mood_overlay:
                    episodic_prefill = mood_overlay.strip() + "\n\n" + episodic_prefill
                speak_filler()
                reply = jb.run_agent_brain(
                    user_utterance=utterance,
                    episodic_prefill=episodic_prefill,
                )
                if reply:
                    speak_reply(reply)
                    remember_last_topic(utterance[:80])
            except JarvisExitRequest:
                speak("Thanks for giving me your precious time Sir")
                raise
            except Exception:
                traceback.print_exc()
                speak("Sir, the reasoning engine hit an error trying that phrase.")
            return

        speak(
            "Sir, nothing in the shorthand command list matched. "
            "Set OPENAI_API_KEY so the conversational brain can take flexible requests "
            "(pip install -r requirements-brain.txt), or phrase it closer to a built-in command."
        )


def run_voice_session(
    *,
    do_greet: bool = True,
    stop_event: Optional[threading.Event] = None,
    on_listening=None,
    on_heard=None,
) -> None:
    """
    Main voice loop. Use jarvis_shell for fullscreen UI + login replacement path.
    """
    try:
        if on_listening or on_heard:
            register_voice_ui_hooks(on_listening=on_listening, on_heard=on_heard)
        if _RAG_AVAILABLE:
            try:
                n_chunks = sync_knowledge_folder()
                if n_chunks:
                    print(f"Knowledge base: indexed {n_chunks} text chunks.", flush=True)
            except Exception:
                traceback.print_exc()
                print("Knowledge base: sync failed (install requirements-rag.txt).", flush=True)
        try:
            from reminders import start_reminder_scheduler

            start_reminder_scheduler(on_fire=lambda m: speak(f"Reminder, Sir: {m}"))
        except Exception:
            traceback.print_exc()

        try:
            from sync_service import start_auto_sync_thread, sync_enabled, sync_pull

            if sync_enabled():
                # Pull latest state from cloud-synced dir before greeting / answering.
                sync_pull()
                start_auto_sync_thread(interval_seconds=300)
        except Exception:
            traceback.print_exc()

        try:
            _start_hotkey_listener()
        except Exception:
            traceback.print_exc()

        try:
            from wake_listener import start_wake_listener

            start_wake_listener()
        except Exception:
            traceback.print_exc()

        try:
            from mic_profile import describe_mic_profile

            print(f"[startup] {describe_mic_profile()}", flush=True)
        except Exception:
            pass

        try:
            from porcupine_wake import available as porc_avail, enabled as porc_on

            if porc_on():
                pass  # start_wake_listener already started Porcupine
            elif porc_avail():
                print("[startup] Porcupine available — set JARVIS_PORCUPINE=auto to enable",
                      flush=True)
        except Exception:
            pass

        try:
            from companion_bridge import register_ask_handler, start_companion_server

            register_ask_handler(_companion_ask)
            start_companion_server()
        except Exception:
            traceback.print_exc()

        if _live_camera_auto():
            try:
                if _start_live_camera():
                    print("[startup] Live camera observer: auto", flush=True)
            except Exception:
                traceback.print_exc()

        if _live_screen_auto():
            try:
                if _start_live_screen():
                    print("[startup] Live screen observer: auto", flush=True)
            except Exception:
                traceback.print_exc()

        try:
            from local_llm import local_llm_mode, ollama_available, ollama_model

            if local_llm_mode() not in ("0", "false", "no", "off"):
                tag = "ready" if ollama_available() else "unreachable"
                print(f"[startup] Local LLM: {tag} ({ollama_model()}, mode={local_llm_mode()})",
                      flush=True)
        except Exception:
            pass

        try:
            from memory.episodic_memory import start_consolidation_daemon

            start_consolidation_daemon(check_seconds=3600)
        except Exception:
            traceback.print_exc()

        try:
            from ambient import start_ambient_daemon

            start_ambient_daemon(speak_reply)
        except Exception:
            traceback.print_exc()

        try:
            from routines import start_routines_daemon

            start_routines_daemon(speak_reply)
        except Exception:
            traceback.print_exc()

        if _sound_monitor_auto_enabled():
            try:
                if _start_sound_monitor():
                    print("[startup] Sound monitor: active (auto)", flush=True)
            except Exception:
                traceback.print_exc()

        try:
            from reflection import schedule_nightly_reflection

            ref_hour = int(os.environ.get("JARVIS_REFLECTION_HOUR", "22"))
            ref_min = int(os.environ.get("JARVIS_REFLECTION_MINUTE", "30"))
            schedule_nightly_reflection(speak, hour=ref_hour, minute=ref_min)
        except Exception:
            traceback.print_exc()

        if do_greet:
            greet()
        passive = _passive_mode_enabled()
        active_session = not passive
        if passive:
            print(
                "[startup] Passive mode ON — say 'Hey Friday' or your wake word before commands "
                "(or press the hotkey). Set JARVIS_PASSIVE_MODE=0 to always listen.",
                flush=True,
            )
        use_wake_daemon = False
        try:
            from wake_listener import enabled as wake_enabled, is_running as wake_running

            use_wake_daemon = wake_enabled() and wake_running()
        except Exception:
            use_wake_daemon = False

        while stop_event is None or not stop_event.is_set():
            was_speaking = _is_speaking()
            raw = ""

            # Background wake listener may have already caught a wake phrase.
            try:
                from wake_listener import pop_wake

                woke_early, after_early = pop_wake()
                if woke_early:
                    active_session = True
                    if after_early:
                        raw = after_early.lower()
            except Exception:
                pass

            if _hotkey_signal.is_set():
                _hotkey_signal.clear()
                active_session = True

            if not raw:
                raw = take_command().lower()
                _apply_speaker_from_capture(get_last_capture_info())

            if _hotkey_signal.is_set():
                _hotkey_signal.clear()
                active_session = True

            if passive and not active_session:
                woke, after_wake = _strip_wake_prefix(raw)
                if not woke:
                    continue
                active_session = True
                if not after_wake:
                    try:
                        from personas import get_address

                        addr = get_address() or "Sir"
                    except Exception:
                        addr = "Sir"
                    speak_reply(f"Yes{', ' + addr if addr else ''}?")
                    continue
                raw = after_wake
            else:
                # Always allow wake-word stripping when present, even in active mode.
                _, raw_stripped = _strip_wake_prefix(raw)
                if raw_stripped:
                    raw = raw_stripped

            if raw != "none" and was_speaking:
                try:
                    from barge_in import classify_interrupt, extract_correction
                    from dialogue_state import close_task

                    kind = classify_interrupt(raw, was_speaking=True)
                    if kind == "stop":
                        try:
                            from personas import get_address

                            addr = get_address()
                        except Exception:
                            addr = ""
                        speak_reply("Okay." + (f" {addr}." if addr else ""))
                        continue
                    if kind == "new_topic":
                        close_task()
                    elif kind == "correction":
                        corrected = extract_correction(raw)
                        if corrected:
                            raw = corrected.lower()
                except Exception:
                    pass

            # Mark the user active for the ambient daemon (resets idle timer).
            try:
                from ambient import mark_user_active

                mark_user_active()
            except Exception:
                pass

            # Topic-thread observation (silent extraction of people/projects mentioned).
            try:
                from topic_threads import observe_utterance

                observe_utterance(raw)
            except Exception:
                pass

            # Pronoun / referent resolution: "do that again", "cancel it", "send that to slack".
            try:
                from dialogue_state import resolve_simple_command

                rewritten = resolve_simple_command(raw)
                if rewritten and rewritten.startswith("__REPLAY_REPLY__::"):
                    replay = rewritten.split("::", 1)[1]
                    speak(replay)
                    continue
                if rewritten:
                    raw = rewritten
            except Exception:
                pass

            try:
                from feedback_learning import try_handle_feedback

                fb = try_handle_feedback(raw)
                if fb:
                    speak_reply(fb)
                    continue
            except Exception:
                pass

            try:
                from post_meeting import try_handle_post_meeting

                pm = try_handle_post_meeting(query, voice_raw=raw)
                if pm:
                    speak_reply(pm)
                    continue
            except Exception:
                pass

            try:
                from routines import try_handle_routine_command

                rt = try_handle_routine_command(query, speak_fn=speak_reply)
                if rt:
                    speak_reply(rt)
                    continue
            except Exception:
                pass

            try:
                from voice_smart_home import try_handle_smart_home

                sh = try_handle_smart_home(query)
                if sh:
                    speak_reply(sh)
                    continue
            except Exception:
                pass

            try:
                from open_loops import observe_utterance as observe_open_loops

                observe_open_loops(raw)
            except Exception:
                pass

            query = normalize_voice_query(raw)
            if query == "none":
                continue

            try:
                from ambient import parse_snooze_command, snooze

                parsed = parse_snooze_command(raw)
                if parsed:
                    category, seconds = parsed
                    snooze(category, seconds)
                    mins = max(1, int(round(seconds / 60)))
                    speak_reply(
                        f"Understood — quiet for about {mins} minute{'s' if mins != 1 else ''}."
                    )
                    continue
            except Exception:
                pass

            try:
                from dialogue_tasks import handle_pending_task

                pending_reply = handle_pending_task(query, raw)
                if pending_reply is not None:
                    speak_reply(pending_reply)
                    continue
            except Exception:
                traceback.print_exc()

            try:
                global _pending_forget
                if _pending_forget is not None:
                    lowq = query.lower().strip()
                    if lowq in {"yes", "yeah", "yep", "confirm", "ok", "sure"}:
                        from memory.episodic_memory import (
                            memory_forget_notes_containing,
                            memory_forget_profile_facts,
                        )

                        if _pending_forget.get("kind") == "profile":
                            deleted = memory_forget_profile_facts()
                        else:
                            deleted = memory_forget_notes_containing(_pending_forget.get("text", ""))

                        speak(f"Done, Sir. Removed {deleted} saved memories.")
                        _pending_forget = None
                        continue

                    if lowq in {"cancel", "no", "nope", "stop"}:
                        speak("Cancelled, Sir.")
                        _pending_forget = None
                        continue

                    speak("Boss, please confirm by saying 'yes' or say 'cancel'.")
                    continue

                # Each pre-step is wrapped so a memory/sentiment/etc. failure
                # never blocks the user's actual command from running.
                try:
                    from memory.episodic_memory import (
                        maybe_summarize_old_turns,
                        memory_append_turn,
                        memory_auto_capture_user_profile,
                    )

                    try:
                        memory_append_turn("user", raw)
                    except Exception:
                        traceback.print_exc()
                    try:
                        memory_auto_capture_user_profile(raw)
                    except Exception:
                        traceback.print_exc()
                    try:
                        maybe_summarize_old_turns()
                    except Exception:
                        traceback.print_exc()
                except Exception:
                    traceback.print_exc()

                try:
                    from sentiment import record_user_mood, recent_mood_label

                    record_user_mood(raw)
                    try:
                        from relationship_memory import observe_turn

                        observe_turn(raw, mood=recent_mood_label())
                    except Exception:
                        pass
                    try:
                        from mood_trajectory import suggest_persona_switch

                        suggested = suggest_persona_switch()
                        if suggested:
                            from personas import get_persona_key, set_persona_key

                            if get_persona_key() != suggested and set_persona_key(suggested):
                                pass  # silent switch; mood overlay handles tone
                    except Exception:
                        pass
                except Exception:
                    pass

                process_command(query, voice_raw=raw)
            except JarvisExitRequest:
                break
            except Exception:
                traceback.print_exc()
                speak("Something went wrong with that command Sir.")
    finally:
        register_voice_ui_hooks()
        try:
            from routines import stop_routines_daemon

            stop_routines_daemon()
        except Exception:
            pass
        try:
            from wake_listener import stop_wake_listener

            stop_wake_listener()
        except Exception:
            pass
        try:
            from companion_bridge import stop_companion_server

            stop_companion_server()
        except Exception:
            pass
        try:
            from sync_service import stop_auto_sync_thread, sync_enabled, sync_push

            if sync_enabled():
                sync_push()
                stop_auto_sync_thread()
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    run_voice_session()