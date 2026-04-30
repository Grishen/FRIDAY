"""Classify user utterances into coarse intents for routing."""

from __future__ import annotations

from enum import Enum


class IntentKind(str, Enum):
    QUESTION = "question"
    TASK = "task"
    REMINDER = "reminder"
    RESEARCH = "research"
    CODING = "coding"
    CALENDAR = "calendar"
    EMAIL = "email"
    MEETING_PREP = "meeting_prep"
    DOCUMENT_SEARCH = "document_search"
    SYSTEM_COMMAND = "system_command"
    SMART_HOME = "smart_home"
    UNKNOWN = "unknown"


class IntentRouter:
    async def classify(self, text: str) -> IntentKind:
        lower = text.lower().strip()
        if any(k in lower for k in ("calendar", "meeting tomorrow", "schedule", "what is on my calendar")):
            return IntentKind.CALENDAR
        if any(k in lower for k in ("email", "inbox", "draft")):
            return IntentKind.EMAIL
        if any(k in lower for k in ("document", "pdf", "file", "rag", "ingested")):
            return IntentKind.DOCUMENT_SEARCH
        if any(k in lower for k in ("research", "look up", "find out")):
            return IntentKind.RESEARCH
        if any(k in lower for k in ("code", "repo", "pr", "pull request")):
            return IntentKind.CODING
        if "prepare" in lower and "meet" in lower:
            return IntentKind.MEETING_PREP
        if "?" in lower or lower.startswith(("what", "why", "how")):
            return IntentKind.QUESTION
        return IntentKind.UNKNOWN
