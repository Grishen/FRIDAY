"""LLM / embedding / vision provider contracts."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChatCompletionProvider(Protocol):
    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class VisionProvider(Protocol):
    async def describe_image(self, *, image_bytes: bytes, prompt: str) -> str: ...
