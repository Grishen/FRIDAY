"""Local LLM fallback via Ollama (or any OpenAI-compatible local server).

Used when cloud API is unavailable, private mode is on, quota is exceeded, or
``JARVIS_LOCAL_LLM=prefer|always``.

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
    return False


def should_prefer_local_first(*, private: bool = False) -> bool:
    """True when cloud should be skipped entirely (always / private-only)."""
    mode = local_llm_mode()
    if not ollama_available():
        return False
    if mode in ("1", "true", "always"):
        return True
    if mode == "private" and private:
        return True
    return False


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.35,
    model: Optional[str] = None,
    tools: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Single non-streaming chat completion against Ollama."""
    url = ollama_base_url()
    if not url:
        raise RuntimeError("JARVIS_OLLAMA_URL not set.")

    payload: dict[str, Any] = {
        "model": model or ollama_model(),
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc


def _message_from_ollama(body: dict[str, Any]) -> dict[str, Any]:
    msg = body.get("message") or {}
    if isinstance(msg, dict):
        return msg
    return {}


def run_local_brain(*, user_utterance: str, episodic_prefill: str) -> str:
    """Tool-free local chat — privacy-friendly fallback when tools aren't available."""
    try:
        from jarvis_brain import brain_system_instructions
    except Exception:
        brain_system_instructions = lambda: "You are a helpful voice assistant."  # type: ignore

    system_text = brain_system_instructions()
    prelude = (episodic_prefill or "").strip()
    if prelude:
        system_text += "\n\nConversation notes:\n" + prelude[:6000]
    system_text += (
        "\n\nYou are running on a LOCAL model without tool access. "
        "Answer from context and general knowledge. Be concise for speech."
    )
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_utterance.strip()},
    ]
    body = chat_completion(messages, temperature=0.38)
    content = (_message_from_ollama(body).get("content") or "").strip()
    if content:
        return content
    raise RuntimeError("Ollama returned an empty reply.")


def run_local_agent_brain(*, user_utterance: str, episodic_prefill: str) -> str:
    """Local Ollama chat with the same tool loop as the cloud brain."""
    from jarvis_brain import (
        TOOL_SPECS,
        brain_max_tool_rounds,
        brain_system_instructions,
        invoke_tool_named,
    )

    prelude = (episodic_prefill or "").strip()
    system_text = brain_system_instructions()
    if prelude:
        system_text += (
            "\n\nConversation notes & recent turns:\n" + prelude[:6000]
        )
    system_text += (
        "\n\nYou are running on a LOCAL model with tool access. "
        "Use tools for real actions (apps, reminders, calendar, search). "
        "Be concise for speech."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_utterance.strip()},
    ]

    for _ in range(brain_max_tool_rounds()):
        body = chat_completion(messages, temperature=0.38, tools=TOOL_SPECS)
        msg = _message_from_ollama(body)
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            return content or "Done, Sir."

        assistant_entry: dict[str, Any] = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [],
        }
        for idx, tc in enumerate(tool_calls):
            fn = tc.get("function") or {}
            fname = str(fn.get("name") or "")
            raw_args = fn.get("arguments")
            if isinstance(raw_args, dict):
                args_str = json.dumps(raw_args)
            else:
                args_str = str(raw_args or "{}")
            tc_id = str(tc.get("id") or f"call_{idx}")
            assistant_entry["tool_calls"].append(
                {
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": fname, "arguments": args_str},
                }
            )
        messages.append(assistant_entry)

        for idx, tc in enumerate(tool_calls):
            fn = tc.get("function") or {}
            fname = str(fn.get("name") or "")
            raw_args = fn.get("arguments")
            if isinstance(raw_args, dict):
                args_str = json.dumps(raw_args)
            else:
                args_str = str(raw_args or "{}")
            tc_id = str(tc.get("id") or f"call_{idx}")
            observations = invoke_tool_named(fname, args_str)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": observations[:12000],
                }
            )

    body = chat_completion(
        messages
        + [{"role": "user", "content": "Summarize what was done succinctly — no tools."}],
        temperature=0.2,
    )
    final = (_message_from_ollama(body).get("content") or "").strip()
    return final or "Pausing here — please restate what you need next."


__all__ = [
    "chat_completion",
    "local_llm_mode",
    "ollama_available",
    "ollama_base_url",
    "ollama_model",
    "run_local_agent_brain",
    "run_local_brain",
    "should_prefer_local_first",
    "should_use_local",
]
