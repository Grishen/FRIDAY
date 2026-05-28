"""Streaming TTS: synthesize and play chunks of speech as they arrive.

Why: with the default speak() path, FRIDAY waits for the *entire* utterance
to be synthesized before any audio plays. For longer answers that means a
noticeable lag. With ``speak_stream(chunks_iterable)`` we synthesize and play
sentence-by-sentence (or chunk-by-chunk), starting the first sound within a
few hundred milliseconds.

Backends used (in order):
    1. ElevenLabs streaming endpoint (``/v1/text-to-speech/{voice_id}/stream``)
    2. Edge-TTS chunked synthesis (per-sentence)
    3. Fallback: simply call existing speak() once with the joined text.

A single ``stop_event`` (threading.Event) can be passed to abort mid-stream,
which is how barge-in stays clean.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Iterable, Optional

import elevenlabs_tts


# --------------------------------------------------------------------------- #
# Sentence chunker
# --------------------------------------------------------------------------- #


_SENT_RE = re.compile(r"(?<=[\.\?\!])\s+|(?<=[\u3002\uFF1F\uFF01])\s*", re.UNICODE)


def chunk_text_for_streaming(text: str, *, max_chars: int = 240) -> list[str]:
    """Split text into chunks roughly aligned to sentence boundaries."""
    text = (text or "").strip()
    if not text:
        return []
    rough = [s.strip() for s in _SENT_RE.split(text) if s.strip()]
    out: list[str] = []
    current = ""
    for s in rough:
        if not current:
            current = s
            continue
        if len(current) + 1 + len(s) <= max_chars:
            current = f"{current} {s}"
        else:
            out.append(current)
            current = s
    if current:
        out.append(current)
    # Final pass: hard-split any single sentence that exceeded max_chars.
    final: list[str] = []
    for s in out:
        if len(s) <= max_chars:
            final.append(s)
        else:
            for i in range(0, len(s), max_chars):
                final.append(s[i : i + max_chars])
    return final


# --------------------------------------------------------------------------- #
# Player helpers
# --------------------------------------------------------------------------- #


def _ffplay_pipe_mp3() -> Optional[subprocess.Popen]:
    """Start an ffplay process that reads MP3 from stdin and plays it."""
    ffplay = shutil.which("ffplay")
    if not ffplay:
        return None
    return subprocess.Popen(
        [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", "pipe:0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _play_mp3_file(path: str) -> None:
    """Reuse elevenlabs_tts.play_mp3 (afplay / ffplay / pygame fallback)."""
    elevenlabs_tts.play_mp3(path)


# --------------------------------------------------------------------------- #
# ElevenLabs streaming backend
# --------------------------------------------------------------------------- #


def _eleven_stream_chunk(text: str, stop_event: threading.Event,
                          *, chunk_settings: Optional[dict] = None) -> bool:
    """Stream a single chunk through ElevenLabs and play via ffplay (if available)."""
    if not elevenlabs_tts.is_configured():
        return False
    try:
        import requests
    except ImportError:
        return False

    api_key = os.environ["ELEVENLABS_API_KEY"]
    voice_id = os.environ["ELEVENLABS_VOICE_ID"]
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    output_format = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
    base_url = os.environ.get("ELEVENLABS_API_BASE", "https://api.elevenlabs.io").rstrip("/")

    url = f"{base_url}/v1/text-to-speech/{voice_id}/stream"
    headers = {"xi-api-key": api_key, "Accept": "audio/mpeg", "Content-Type": "application/json"}
    body = {"text": text, "model_id": model_id}

    # Layered voice settings: prosody per chunk > mood overlay > persona defaults.
    voice_settings: dict = {}
    try:
        from prosody import voice_settings_for_chunk

        base: dict = {}
        try:
            from voice_emotion import current_voice_settings

            base = current_voice_settings() or {}
        except Exception:
            try:
                from personas import get_persona

                base = dict(get_persona().get("voice") or {})
            except Exception:
                base = {}
        voice_settings = voice_settings_for_chunk(text, chunk_settings or base)
    except Exception:
        try:
            from voice_emotion import current_voice_settings

            voice_settings = current_voice_settings() or {}
        except Exception:
            try:
                from personas import get_persona

                voice_settings = dict(get_persona().get("voice") or {})
            except Exception:
                voice_settings = {}
    style = os.environ.get("ELEVENLABS_STYLE",
                           str(voice_settings.get("style", "")) or None)
    stability = os.environ.get("ELEVENLABS_STABILITY",
                               str(voice_settings.get("stability", "")) or None)
    similarity = os.environ.get("ELEVENLABS_SIMILARITY",
                                str(voice_settings.get("similarity", "")) or None)
    use_speaker_boost = os.environ.get("ELEVENLABS_SPEAKER_BOOST",
                                       str(voice_settings.get("speaker_boost", "")) or None)
    if any(v is not None for v in (style, stability, similarity, use_speaker_boost)):
        body["voice_settings"] = {}
        if stability is not None:
            try:
                body["voice_settings"]["stability"] = float(stability)
            except ValueError:
                pass
        if similarity is not None:
            try:
                body["voice_settings"]["similarity_boost"] = float(similarity)
            except ValueError:
                pass
        if style is not None:
            try:
                body["voice_settings"]["style"] = float(style)
            except ValueError:
                pass
        if use_speaker_boost is not None:
            body["voice_settings"]["use_speaker_boost"] = str(use_speaker_boost).lower() in ("1", "true", "yes")

    try:
        resp = requests.post(
            url, params={"output_format": output_format},
            json=body, headers=headers, timeout=120, stream=True,
        )
        resp.raise_for_status()
    except Exception:
        return False

    player = _ffplay_pipe_mp3()
    if player is not None and player.stdin is not None:
        try:
            for chunk in resp.iter_content(chunk_size=4096):
                if stop_event.is_set():
                    break
                if not chunk:
                    continue
                try:
                    player.stdin.write(chunk)
                    player.stdin.flush()
                except (BrokenPipeError, OSError):
                    break
        finally:
            try:
                player.stdin.close()
            except Exception:
                pass
            try:
                player.wait(timeout=30)
            except Exception:
                player.kill()
        return True

    # No ffplay → save then play.
    fd, path = tempfile.mkstemp(suffix=".mp3")
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if stop_event.is_set():
                    break
                if chunk:
                    f.write(chunk)
        if not stop_event.is_set():
            _play_mp3_file(path)
        return True
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Edge-TTS chunked backend
# --------------------------------------------------------------------------- #


def _edge_chunk(text: str, stop_event: threading.Event) -> bool:
    try:
        import jarvis_edge_tts as jet
    except ImportError:
        return False
    if not (jet.edge_enabled() and jet.is_available()):
        return False
    if stop_event.is_set():
        return True
    try:
        return jet.synthesize_and_play(text)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Streaming orchestrator
# --------------------------------------------------------------------------- #


def speak_stream(
    chunks: Iterable[str],
    *,
    stop_event: Optional[threading.Event] = None,
    on_chunk_start: Optional[Callable[[str], None]] = None,
    on_chunk_end: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Speak chunks as they arrive. Returns the fully spoken text.

    The chunks iterable can be a generator that yields partial sentences from an
    LLM stream. Each chunk is synthesized + played sequentially, so the listener
    hears speech start almost immediately.
    """
    stop_event = stop_event or threading.Event()
    force_local = os.environ.get("JARVIS_USE_LOCAL_TTS", "").lower() in ("1", "true", "yes")
    eleven_only = os.environ.get("JARVIS_ELEVENLABS_ONLY", "").lower() in ("1", "true", "yes")
    use_eleven = (not force_local) and elevenlabs_tts.is_configured()

    spoken: list[str] = []
    for chunk in chunks:
        if stop_event.is_set():
            break
        chunk = (chunk or "").strip()
        if not chunk:
            continue
        if on_chunk_start:
            try:
                on_chunk_start(chunk)
            except Exception:
                pass

        played = False
        if use_eleven:
            try:
                played = _eleven_stream_chunk(chunk, stop_event)
            except Exception:
                played = False
            if not played and eleven_only:
                # ElevenLabs-only mode failed: stop trying further fallbacks.
                break
        if not played and not force_local and not eleven_only:
            played = _edge_chunk(chunk, stop_event)
        if not played and not eleven_only:
            try:
                import pyttsx3  # type: ignore

                eng = pyttsx3.init()
                eng.say(chunk)
                eng.runAndWait()
                played = True
            except Exception:
                played = False
        if played:
            spoken.append(chunk)
            try:
                from prosody import pause_after_chunk

                pause_s = pause_after_chunk(chunk)
                if pause_s > 0 and not stop_event.is_set():
                    time.sleep(pause_s)
            except Exception:
                pass
        if on_chunk_end:
            try:
                on_chunk_end(chunk)
            except Exception:
                pass

    return " ".join(spoken)


def speak_stream_text(
    text: str,
    *,
    stop_event: Optional[threading.Event] = None,
    max_chars: int = 240,
) -> str:
    """Convenience: chunk a full string and speak it as a stream."""
    return speak_stream(chunk_text_for_streaming(text, max_chars=max_chars),
                        stop_event=stop_event)


__all__ = [
    "chunk_text_for_streaming",
    "speak_stream",
    "speak_stream_text",
]
