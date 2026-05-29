import datetime as dt

from reminders import parse_reminder


def test_parse_reminder_relative_minutes() -> None:
    msg, due, recurrence = parse_reminder("remind me to call mom in 5 minutes")
    assert "call mom" in msg.lower()
    assert due is not None
    assert recurrence == ""
    assert due > dt.datetime.now() - dt.timedelta(seconds=30)


def test_parse_reminder_at_time() -> None:
    msg, due, recurrence = parse_reminder("remind me to take pills at 9pm")
    assert due is not None
    assert due.hour == 21
    assert recurrence == ""


def test_parse_reminder_weekday_recurrence() -> None:
    msg, due, recurrence = parse_reminder("remind me to stretch every weekday at 3pm")
    assert recurrence == "weekdays"
    assert due is not None


def test_parse_reminder_empty() -> None:
    msg, due, recurrence = parse_reminder("")
    assert msg == ""
    assert due is None
    assert recurrence == ""
