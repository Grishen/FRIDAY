"""ElevenLabs cloud TTS: uses your API key and voice_id (cloned voice)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

import requests


def _parse_env_file(path: str) -> None:
    """Load KEY=value pairs into os.environ if not already set (no python-dotenv required)."""
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
            os.environ[key] = val


def _load_dotenv_if_present() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except ImportError:
        _parse_env_file(env_path)


_load_dotenv_if_present()


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
