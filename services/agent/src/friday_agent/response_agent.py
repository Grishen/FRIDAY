"""Natural-language response generation — backed by provider in API."""

from __future__ import annotations

from pydantic import BaseModel


class AssistantPersona(BaseModel):
    name: str = "FRIDAY"
    tone: str = "calm sharp professional"
    default_response_length: str = "concise"
    humor_level: str = "light"
    proactivity: str = "moderate"
    approval_style: str = "clear"


class ResponseAgent:
    def __init__(self, persona: AssistantPersona | None = None) -> None:
        self.persona = persona or AssistantPersona()

    async def render(self, content: str, *, mode: str = "quick") -> str:
        if mode == "silent_execution":
            return ""
        header = f"[{self.persona.name}] "
        return header + content.strip()
