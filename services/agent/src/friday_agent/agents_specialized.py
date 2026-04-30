"""Research, coding, critic, security agents — skeleton implementations."""

from __future__ import annotations


class ResearchAgent:
    async def summarize_sources(self, sources: list[str]) -> str:
        return "Summary: " + "; ".join(sources[:3])


class CodingAgent:
    async def summarize_repo_intent(self, repo_hint: str) -> str:
        return f"Coding assistance scope: {repo_hint}"


class CriticAgent:
    async def critique(self, draft_answer: str) -> list[str]:
        missing: list[str] = []
        if len(draft_answer) < 10:
            missing.append("expand_context")
        return missing


class SecurityAgent:
    async def screen(self, text: str) -> tuple[bool, list[str]]:
        flagged: list[str] = []
        lowered = text.lower()
        if "ignore previous" in lowered or "system prompt" in lowered:
            flagged.append("possible_prompt_injection")
        return (len(flagged) == 0), flagged
