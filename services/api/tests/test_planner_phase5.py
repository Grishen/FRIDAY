"""Planner + intent wiring (Phase 5)."""

import asyncio

from friday_agent.intent_router import IntentKind
from friday_agent.planner import PlanSpec, PlannerAgent


def _run(plan_coro) -> PlanSpec:
    return asyncio.run(plan_coro)


def test_planner_filters_to_available_registry() -> None:
    async def go() -> PlanSpec:
        return await PlannerAgent().plan(
            "check email",
            {
                "intent": IntentKind.EMAIL.value,
                "available_tools": ["email.search"],
                "memory_snippets": [],
            },
        )

    plan = _run(go())
    assert plan.required_tools == ["email.search"]


def test_planner_send_path_requires_registry() -> None:
    async def go() -> PlanSpec:
        return await PlannerAgent().plan(
            "please send the recap",
            {
                "intent": IntentKind.UNKNOWN.value,
                "available_tools": ["email.send", "calendar.read_events"],
                "memory_snippets": [],
            },
        )

    plan = _run(go())
    assert "email.send" in plan.required_tools
    assert plan.required_tools[0] == "email.send"


def test_planner_doc_intent() -> None:
    async def go() -> PlanSpec:
        return await PlannerAgent().plan(
            "search the uploaded pdf",
            {
                "intent": IntentKind.DOCUMENT_SEARCH.value,
                "available_tools": ["documents.ask"],
                "memory_snippets": [],
            },
        )

    plan = _run(go())
    assert plan.required_tools == ["documents.ask"]
