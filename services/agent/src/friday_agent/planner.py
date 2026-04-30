"""Structured planning — intent-aware steps, validated against the live tool catalog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from friday_agent.intent_router import IntentKind


class PlanSpec(BaseModel):
    goal: str = ""
    assumptions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    approval_points: list[str] = Field(default_factory=list)
    expected_output: str = ""


def _avail_set(raw: Any) -> set[str]:
    if not raw:
        return set()
    if isinstance(raw, list):
        return {str(x) for x in raw}
    return set()


def _maybe_pick_local_tools(
    *,
    user_lower: str,
    available: set[str],
    add: Callable[[str], None],
) -> None:
    if not any(x.startswith("local.") for x in available):
        return
    if any(
        k in user_lower
        for k in (
            "list files",
            "list folder",
            "list directory",
            "workspace",
            "files in ",
            "directories",
            "what's in",
            "whats in",
        )
    ):
        add("local.list_directory")
    if any(k in user_lower for k in ("read file", "file contents", "show file", "open file ", "dump file")):
        add("local.read_file")
    if any(k in user_lower for k in ("write file", "save file", "create file", "overwrite file")):
        add("local.write_file")
    if any(k in user_lower for k in ("open app", "launch app", "start app", "open application", "launch ")):
        add("local.open_application")
    if any(k in user_lower for k in ("quit app", "close app", "stop app", "exit app")):
        add("local.quit_application")


def _pick_tools(*, intent: str, user_lower: str, available: set[str]) -> list[str]:
    """Order tools by intent + keywords; only names present in ``available``."""

    out: list[str] = []

    def add(name: str) -> None:
        if name in available and name not in out:
            out.append(name)

    if "send" in user_lower:
        add("email.send")
        add("calendar.read_events")
        return out[:6]

    _maybe_pick_local_tools(user_lower=user_lower, available=available, add=add)

    if intent == IntentKind.CALENDAR.value:
        add("calendar.read_events")
    elif intent == IntentKind.EMAIL.value:
        add("email.search")
        add("calendar.read_events")
    elif intent in (IntentKind.DOCUMENT_SEARCH.value, IntentKind.RESEARCH.value):
        add("documents.ask")
    elif intent == IntentKind.MEETING_PREP.value:
        add("calendar.read_events")
        add("email.search")
        add("documents.ask")
    elif intent == IntentKind.CODING.value:
        add("documents.ask")
    else:
        add("calendar.read_events")
        add("email.search")
        add("documents.ask")

    return out[:6]


class PlannerAgent:
    async def plan(self, user_text: str, context: dict[str, Any]) -> PlanSpec:
        intent = str(context.get("intent") or IntentKind.UNKNOWN.value)
        available = _avail_set(context.get("available_tools"))
        lower = user_text.lower()
        memory_n = len(context.get("memory_snippets") or [])

        required = _pick_tools(intent=intent, user_lower=lower, available=available)

        assumptions = [
            "tools_filtered_to_gateway_registry",
            "user_timezone_local",
        ]
        if memory_n:
            assumptions.append(f"memory_hits_{memory_n}")

        steps = [f"intent={intent}"]
        for t in required:
            steps.append(f"invoke:{t}")

        approval_points = [t for t in required if t.endswith(".send") or "write" in t or "open_application" in t or "quit_application" in t]

        return PlanSpec(
            goal=user_text,
            assumptions=assumptions,
            steps=steps,
            required_tools=required,
            approval_points=approval_points,
            expected_output="Answer grounded in tool JSON + retrieved context",
        )
