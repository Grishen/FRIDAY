"""ElevenLabs cloud TTS: uses your API key and voice_id (cloned voice)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

import requests


def _parse_env_file(path: str) -> int:
    """Load KEY=value pairs into os.environ if not already set. Returns count loaded."""
    n = 0
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            val = val.strip().strip('"').strip("'")
            if not val:
                # Skip empty placeholders so they don't shadow real values.
                continue
            os.environ[key] = val
            n += 1
    return n


_LOADED_ENV_FROM: str = ""


def _load_dotenv_if_present() -> None:
    """
    Load `.env` if present; else fall back to `.env.template`. This is forgiving
    so users who fill in `.env.template` directly still get their keys loaded
    (with a clear warning recommending the proper rename).
    """
    global _LOADED_ENV_FROM
    here = os.path.dirname(os.path.abspath(__file__))
    primary = os.path.join(here, ".env")
    template = os.path.join(here, ".env.template")

    target: str | None = None
    if os.path.isfile(primary):
        target = primary
    elif os.path.isfile(template):
        target = template
        print(
            "[env] No .env found — loading .env.template instead. "
            "Recommended: `cp .env.template .env` so future updates to the template don't affect you."
        )

    if not target:
        return

    try:
        from dotenv import load_dotenv

        load_dotenv(target)
        _LOADED_ENV_FROM = target
    except ImportError:
        if _parse_env_file(target) > 0:
            _LOADED_ENV_FROM = target


_load_dotenv_if_present()


def loaded_env_path() -> str:
    return _LOADED_ENV_FROM


def is_configured() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID"))


def play_mp3(path: str) -> None:
    """Play an MP3 file using the best option on this system."""
    if sys.platform == "darwin" and shutil.which("afplay"):
        subprocess.run(["afplay", path], check=False)
        return
    ffplay = shutil.which("ffplay")
    if ffplay:
        subprocess.run(
            [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        import pygame  # type: ignore[import-untyped]

        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(50)
    except Exception as exc:
        raise RuntimeError(
            "Cannot play MP3: on macOS, afplay should be available; on other systems install "
            "ffmpeg (ffplay) or pip install pygame."
        ) from exc


def synthesize_and_play(text: str) -> bool:
    """
    Generate speech via ElevenLabs and play it locally. Returns True if audio was played.
    Returns False if ElevenLabs env is not configured (caller should use local TTS).
    Raises on HTTP / playback errors when configured.
    """
    stripped = (text or "").strip()
    if not stripped:
        return True
    if not is_configured():
        return False

    api_key = os.environ["ELEVENLABS_API_KEY"]
    voice_id = os.environ["ELEVENLABS_VOICE_ID"]
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    output_format = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
    base_url = os.environ.get("ELEVENLABS_API_BASE", "https://api.elevenlabs.io").rstrip("/")

    url = f"{base_url}/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {"text": stripped, "model_id": model_id}
    resp = requests.post(
        url,
        params={"output_format": output_format},
        json=body,
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()

    fd, path = tempfile.mkstemp(suffix=".mp3")
    try:
        os.write(fd, resp.content)
        os.close(fd)
        fd = -1
        play_mp3(path)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(path)
        except OSError:
            pass
    return True
