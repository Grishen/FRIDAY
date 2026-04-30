"""Register default tools into the gateway."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from friday_tools import RegisteredTool, RiskLevel, ToolRegistry

from friday_api.services.local_host_handlers import (
    tool_local_list_directory,
    tool_local_open_application,
    tool_local_quit_application,
    tool_local_read_file,
    tool_local_write_file,
)


async def mock_calendar_read_events(**_: object) -> dict:
    return {
        "events": [
            {"title": "Design review", "start": "2026-04-28T15:00:00Z"},
            {"title": "1:1 with manager", "start": "2026-04-28T17:00:00Z"},
        ]
    }


_DOC_IN = {"type": "object", "properties": {"query": {"type": "string", "minLength": 1}}, "required": ["query"]}


async def rag_documents_ask(query: str, user_id: UUID, **_kw: Any) -> dict[str, Any]:
    from friday_api.db.session import SessionLocal
    from friday_api.services.rag_service import answer_with_rag

    async with SessionLocal() as session:
        out = await answer_with_rag(session, user_id=user_id, query=query)
        return dict(out)


async def mock_email_search(**_: object) -> dict:
    return {"threads": [{"subject": "(mock) Re: roadmap", "unread": True}]}


async def mock_email_send(**kwargs: Any) -> dict:
    to = kwargs.get("to", "unknown")
    return {"sent": True, "to": to, "message_id": "mock-msg-123"}


_SH_LIST_OUT = {
    "type": "object",
    "properties": {"items": {"type": "array"}},
    "required": ["items"],
}
_SH_SET_IN = {
    "type": "object",
    "properties": {
        "device_key": {"type": "string", "minLength": 1},
        "state": {"type": "object"},
    },
    "required": ["device_key", "state"],
}
_SH_SET_OUT = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "device": {"type": "object"},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}

_LOCAL_FS_OUT = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "path": {"type": "string"},
        "content": {"type": "string"},
        "entries": {"type": "array"},
        "bytes_written": {"type": "integer"},
        "limit_bytes": {"type": "integer"},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}
_LOCAL_LIST_IN = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "additionalProperties": False,
}
_LOCAL_RD_IN = {
    "type": "object",
    "properties": {"path": {"type": "string", "minLength": 1}},
    "required": ["path"],
    "additionalProperties": False,
}
_LOCAL_WR_IN = {
    "type": "object",
    "properties": {"path": {"type": "string", "minLength": 1}, "content": {"type": "string"}},
    "required": ["path", "content"],
    "additionalProperties": False,
}
_LOCAL_APP_IN = {
    "type": "object",
    "properties": {"app": {"type": "string", "minLength": 1}},
    "required": ["app"],
    "additionalProperties": False,
}
_APP_ACTION_OUT = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "app": {"type": "string"},
        "platform": {"type": "string"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["ok"],
}


async def tool_smarthome_list_devices(user_id: UUID, **_kw: Any) -> dict[str, Any]:
    from friday_api.db.session import SessionLocal
    from friday_api.services import smart_home_service

    async with SessionLocal() as session:
        rows = await smart_home_service.list_devices(session, user_id=user_id)
        return {"items": rows}


async def tool_smarthome_set_device_state(
    device_key: str, state: dict[str, Any], user_id: UUID, **_kw: Any
) -> dict[str, Any]:
    from friday_api.db.session import SessionLocal
    from friday_api.services import smart_home_service

    async with SessionLocal() as session:
        row = await smart_home_service.patch_device_state(
            session, user_id=user_id, device_key=device_key, patch=state
        )
        if not row:
            return {"ok": False, "error": "unknown_device"}
        await session.commit()
        return {"ok": True, "device": row}


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    meta = [
        RegisteredTool(
            name="calendar.read_events",
            description="Read upcoming calendar events",
            risk_level=RiskLevel.LOW,
            requires_approval=False,
        ),
        RegisteredTool(
            name="documents.ask",
            description="Ask questions over ingested documents (tenant-scoped chunks + citations)",
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            input_schema=_DOC_IN,
            output_schema={
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "citations": {"type": "array"},
                },
                "required": ["answer", "citations"],
            },
        ),
        RegisteredTool(
            name="email.search",
            description="Search email threads (mock)",
            risk_level=RiskLevel.LOW,
            requires_approval=False,
        ),
        RegisteredTool(
            name="email.send",
            description="Send an email (mock, high risk)",
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
        ),
        RegisteredTool(
            name="smarthome.list_devices",
            description="List stub smart home devices + current state",
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            output_schema=_SH_LIST_OUT,
        ),
        RegisteredTool(
            name="smarthome.set_device_state",
            description="Update stub smart home device state (lights, plugs, thermostat, lock)",
            risk_level=RiskLevel.MEDIUM,
            requires_approval=False,
            input_schema=_SH_SET_IN,
            output_schema=_SH_SET_OUT,
        ),
        RegisteredTool(
            name="local.list_directory",
            description="List files under FRIDAY_LOCAL_WORKSPACE (sandboxed)",
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            input_schema=_LOCAL_LIST_IN,
            output_schema=_LOCAL_FS_OUT,
        ),
        RegisteredTool(
            name="local.read_file",
            description="Read a UTF-8 text file inside FRIDAY_LOCAL_WORKSPACE",
            risk_level=RiskLevel.MEDIUM,
            requires_approval=False,
            input_schema=_LOCAL_RD_IN,
            output_schema=_LOCAL_FS_OUT,
        ),
        RegisteredTool(
            name="local.write_file",
            description="Write UTF-8 text into FRIDAY_LOCAL_WORKSPACE (requires approval)",
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            input_schema=_LOCAL_WR_IN,
            output_schema=_LOCAL_FS_OUT,
        ),
        RegisteredTool(
            name="local.open_application",
            description="Open a GUI app from FRIDAY_OPEN_APP_ALLOWLIST only (requires approval)",
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            input_schema=_LOCAL_APP_IN,
            output_schema=_APP_ACTION_OUT,
        ),
        RegisteredTool(
            name="local.quit_application",
            description="Gracefully quit an app via AppleScript — allowlist only; macOS (requires approval)",
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            input_schema=_LOCAL_APP_IN,
            output_schema=_APP_ACTION_OUT,
        ),
    ]
    handlers = [
        mock_calendar_read_events,
        rag_documents_ask,
        mock_email_search,
        mock_email_send,
        tool_smarthome_list_devices,
        tool_smarthome_set_device_state,
        tool_local_list_directory,
        tool_local_read_file,
        tool_local_write_file,
        tool_local_open_application,
        tool_local_quit_application,
    ]
    for m, h in zip(meta, handlers, strict=True):
        reg.register(m, h)
    return reg
