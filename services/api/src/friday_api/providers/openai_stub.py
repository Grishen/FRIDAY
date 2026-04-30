"""OpenAI-compatible adapter (wire API keys in later phases)."""

from __future__ import annotations

from friday_api.providers.base import ChatCompletionProvider


class OpenAIChatStub(ChatCompletionProvider):
    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        raise NotImplementedError("configure OPENAI_API_KEY and implement httpx call")
