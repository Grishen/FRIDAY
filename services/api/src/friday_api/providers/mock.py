"""Deterministic mock providers for local development and tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

from friday_api.providers.base import ChatCompletionProvider, EmbeddingProvider, VisionProvider


class MockChatProvider(ChatCompletionProvider):
    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        last = messages[-1]["content"] if messages else ""
        return f"(mock-llm) {last[:500]}"

    async def astream(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        full = await self.complete(messages=messages, model=model, temperature=temperature)
        step = max(8, len(full) // 24)
        for i in range(0, len(full), step):
            yield full[i : i + step]


class MockEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            seed = int.from_bytes(h[:8], "big")
            vec = [((seed >> (i % 8)) % 97) / 233.0 - 0.2 for i in range(self.dimensions)]
            out.append(vec)
        return out


class MockVisionProvider(VisionProvider):
    async def describe_image(self, *, image_bytes: bytes, prompt: str) -> str:
        return f"(mock-vision) bytes={len(image_bytes)} prompt={prompt[:120]}"
