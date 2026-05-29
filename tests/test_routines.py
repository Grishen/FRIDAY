from routines import parse_and_create_routine


def test_parse_and_create_schedule_routine() -> None:
    result = parse_and_create_routine("every weekday at 8 am daily briefing")
    assert "Routine #" in result
    assert "briefing" in result.lower()


def test_parse_and_create_focus_routine() -> None:
    result = parse_and_create_routine(
        "when I am in Xcode enable glance mode and daily briefing"
    )
    assert "Routine #" in result
    assert "xcode" in result.lower()


def test_parse_and_create_rejects_missing_time() -> None:
    result = parse_and_create_routine("daily briefing")
    assert "Include a time" in result
