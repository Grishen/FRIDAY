"""Local LLM fallback via Ollama (or any OpenAI-compatible local server).

Used when cloud API is unavailable, private mode is on, or
``JARVIS_LOCAL_LLM=prefer``.

Env:
    JARVIS_LOCAL_LLM=0|prefer|always|private
    JARVIS_OLLAMA_URL=http://localhost:11434
    JARVIS_OLLAMA_MODEL=llama3.2
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional


def ollama_base_url() -> str:
    return (os.environ.get("JARVIS_OLLAMA_URL", "http://localhost:11434") or "").rstrip("/")


def ollama_model() -> str:
    return (os.environ.get("JARVIS_OLLAMA_MODEL", "llama3.2") or "llama3.2").strip()


def ollama_available() -> bool:
    url = ollama_base_url()
    if not url:
        return False
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def local_llm_mode() -> str:
    return (os.environ.get("JARVIS_LOCAL_LLM", "0") or "0").strip().lower()


def should_use_local(*, private: bool = False, cloud_key_missing: bool = False) -> bool:
    mode = local_llm_mode()
    if mode in ("0", "false", "no", "off"):
        return False
    if not ollama_available():
        return False
    if mode in ("1", "true", "always"):
        return True
    if mode == "prefer" and (cloud_key_missing or private):
        return True
    if mode == "private" and private:
        return True
    if mode == "prefer":
        return cloud_key_missing
    return False


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.35,
    model: Optional[str] = None,
) -> str:
    """Single non-streaming chat completion against Ollama."""
    url = ollama_base_url()
    if not url:
        raise RuntimeError("JARVIS_OLLAMA_URL not set.")

    payload = {
        "model": model or ollama_model(),
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    msg = body.get("message") or {}
    content = (msg.get("content") or "").strip()
    if content:
        return content
    raise RuntimeError("Ollama returned an empty reply.")


def run_local_brain(*, user_utterance: str, episodic_prefill: str) -> str:
    """Tool-free local chat — privacy-friendly, works offline."""
    try:
        from jarvis_brain import brain_system_instructions
    except Exception:
        brain_system_instructions = lambda: "You are a helpful voice assistant."  # type: ignore

    system_text = brain_system_instructions()
    prelude = (episodic_prefill or "").strip()
    if prelude:
        system_text += (
            "\n\nConversation notes:\n" + prelude[:6000]
        )
    system_text += (
        "\n\nYou are running on a LOCAL model without tool access. "
        "Answer from context and general knowledge. Be concise for speech. "
        "If an action requires tools (open apps, web, vision), say what you "
        "would do and ask the user to repeat when cloud brain is available."
    )
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_utterance.strip()},
    ]
    return chat_completion(messages, temperature=0.38)


__all__ = [
    "chat_completion",
    "local_llm_mode",
    "ollama_available",
    "ollama_base_url",
    "ollama_model",
    "run_local_brain",
    "should_use_local",
]
