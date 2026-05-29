from dialogue_state import (
    close_task,
    get_last_reply,
    open_task,
    remember_last_reply,
    resolve_simple_command,
    update_task_slot,
)


def test_resolve_undo_last() -> None:
    assert resolve_simple_command("cancel it") == "undo last"


def test_resolve_replay_last_reply() -> None:
    remember_last_reply("Weather is sunny today.")
    result = resolve_simple_command("say that again")
    assert result == "__REPLAY_REPLY__::Weather is sunny today."


def test_resolve_slack_from_last_reply() -> None:
    remember_last_reply("Ship the report by noon.")
    assert resolve_simple_command("send that to slack") == "slack Ship the report by noon."


def test_pending_task_slots() -> None:
    close_task()
    open_task("calendar", slots={"title": "Standup"}, prompt="When?")
    task = update_task_slot("start", "tomorrow at 9am")
    assert task is not None
    assert task["slots"]["title"] == "Standup"
    assert task["slots"]["start"] == "tomorrow at 9am"
    closed = close_task()
    assert closed is not None
    assert closed["name"] == "calendar"
