"""OpenAI-compatible chat completions with optional streaming deltas."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class OpenAICompatibleChatProvider:
    """HTTPS client for ``/v1/chat/completions`` (OpenAI and many proxies)."""

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        buf: list[str] = []
        async for chunk in self.astream(messages=messages, model=model, temperature=temperature):
            buf.append(chunk)
        return "".join(buf)

    async def astream(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        if not self._api_key:
            return
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        obj: dict[str, Any] = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0] or {}).get("delta") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        yield piece
