import json

import jarvis_brain as jb


def test_tool_specs_include_core_tools() -> None:
    names = {spec["function"]["name"] for spec in jb.TOOL_SPECS}
    for required in (
        "set_reminder",
        "calendar_list_today",
        "launch_local_app",
        "get_weather",
        "describe_screen",
    ):
        assert required in names


def test_invoke_current_time() -> None:
    result = jb.invoke_tool_named("current_time", "{}")
    assert result
    assert any(ch.isdigit() for ch in result)


def test_invoke_tell_joke() -> None:
    result = jb.invoke_tool_named("tell_random_joke", "{}")
    assert len(result.strip()) > 5


def test_invoke_unknown_tool() -> None:
    result = jb.invoke_tool_named("not_a_real_tool", "{}")
    assert "No handler" in result


def test_invoke_set_reminder_requires_fields() -> None:
    result = jb.invoke_tool_named("set_reminder", json.dumps({"message": "stretch"}))
    assert "Need both" in result
