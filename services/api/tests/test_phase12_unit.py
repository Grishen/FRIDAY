"""Direct unit coverage for mocks + bootstrap helpers (Phase 12)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from friday_api.db.session import SessionLocal
from friday_api.models import User
from friday_api.tooling.bootstrap import (
    mock_calendar_read_events,
    mock_email_search,
    mock_email_send,
    tool_smarthome_list_devices,
    tool_smarthome_set_device_state,
)


@pytest.mark.asyncio
async def test_bootstrap_calendar_and_email_helpers() -> None:
    ev = await mock_calendar_read_events()
    assert "events" in ev
    inbox = await mock_email_search()
    assert "threads" in inbox
    sent = await mock_email_send(to="a@example.com")
    assert sent.get("sent") is True


@pytest.mark.asyncio
async def test_bootstrap_smart_home_tools_with_user_row() -> None:
    uid = uuid4()

    naked = await tool_smarthome_list_devices(user_id=uid)
    assert isinstance(naked["items"], list)

    async with SessionLocal() as session:
        session.add(User(id=uid, email=f"{uid.hex[:12]}@stub.local"))
        await session.commit()

    out = await tool_smarthome_set_device_state(
        device_key="kitchen.switch_coffee", state={"on": True}, user_id=uid
    )
    assert out.get("ok") is True
    assert isinstance(out["device"]["state"], dict)
