"""Select chat provider from settings (mock vs OpenAI-compatible)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from friday_api.config import Settings


def get_chat_provider(settings: "Settings"):
    """Return a provider with ``complete`` + ``astream`` (async iterable of text chunks)."""

    if settings.openai_api_key.strip():
        from friday_api.providers.openai_chat import OpenAICompatibleChatProvider

        return OpenAICompatibleChatProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_chat_model,
        )
    from friday_api.providers.mock import MockChatProvider

    return MockChatProvider()
