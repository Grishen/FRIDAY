from calendar_service import (
    calendar_backend_name,
    calendar_unavailable_message,
    parse_calendar_phrase,
)


def test_parse_calendar_phrase_lunch() -> None:
    title, start, duration = parse_calendar_phrase("lunch with Sam tomorrow at 12:30 for 1 hour")
    assert "lunch" in title.lower() or "sam" in title.lower()
    assert start is not None
    assert start.hour == 12
    assert start.minute == 30
    assert duration == 60


def test_parse_calendar_phrase_defaults() -> None:
    title, start, duration = parse_calendar_phrase("")
    assert title == ""
    assert start is None
    assert duration == 30


def test_calendar_unavailable_message_mentions_caldav() -> None:
    assert "CalDAV" in calendar_unavailable_message()


def test_calendar_backend_name_without_config() -> None:
    # No macOS Calendar or CalDAV in CI — should be empty string.
    assert calendar_backend_name() in ("", "macOS Calendar", "CalDAV")
