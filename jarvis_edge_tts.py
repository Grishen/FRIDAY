"""Microsoft Edge-style neural voices (online) via ``edge-tts`` — typically free for personal use.

Requires network + ``pip install edge-tts``. Audio is synthesized to a temp MP3 and played via
:class:`elevenlabs_tts.play_mp3` (ffplay/pygame/macOS ``afplay``).

Env:
  JARVIS_EDGE_TTS — ``1``/``on`` (default when this module is used) or ``0`` to skip
  JARVIS_EDGE_TTS_VOICE — e.g. ``en-US-AriaNeural``, ``en-GB-RyanNeural`` (list: ``edge-tts --list-voices``)
  JARVIS_EDGE_TTS_RATE — e.g. ``+0%``, ``+10%``
  JARVIS_EDGE_TTS_PITCH — e.g. ``+0Hz``, ``+2Hz``
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import elevenlabs_tts


def is_available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return True


def edge_enabled() -> bool:
    return os.environ.get("JARVIS_EDGE_TTS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def default_voice() -> str:
    return (
        os.environ.get("JARVIS_EDGE_TTS_VOICE", "en-US-AriaNeural").strip()
        or "en-US-AriaNeural"
    )


async def _save_mp3(text: str, out_path: str, voice: str, rate: str, pitch: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)


def synthesize_and_play(text: str) -> bool:
    """Return True if audio was played; False if edge-tts missing/disabled/empty."""
    if not edge_enabled() or not is_available():
        return False
    stripped = (text or "").strip()
    if not stripped:
        return True

    voice = default_voice()
    rate = os.environ.get("JARVIS_EDGE_TTS_RATE", "+0%").strip() or "+0%"
    pitch = os.environ.get("JARVIS_EDGE_TTS_PITCH", "+0Hz").strip() or "+0Hz"

    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        asyncio.run(_save_mp3(stripped, path, voice, rate, pitch))
        elevenlabs_tts.play_mp3(path)
        return True
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
