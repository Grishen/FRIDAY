import os

import pytest

from jarvis_exceptions import JarvisExitRequest
from voice_router import (
    brain_first_enabled,
    help_text,
    is_fast_path,
    normalize_voice_query,
    try_fast_path,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", "none"),
        ("none", "none"),
        ("Hey Friday, open Safari", "open safari"),
        ("please can you tell me the time", "tell me time"),
        ("okay open the calculator", "open calculator"),
    ],
)
def test_normalize_voice_query(raw: str, expected: str) -> None:
    assert normalize_voice_query(raw) == expected


def test_brain_first_defaults_on() -> None:
    os.environ.pop("JARVIS_BRAIN_FIRST", None)
    assert brain_first_enabled() is True


def test_brain_first_can_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_BRAIN_FIRST", "0")
    assert brain_first_enabled() is False


@pytest.mark.parametrize(
    "query,fast",
    [
        ("exit", True),
        ("please exit now", True),
        ("help", True),
        ("volume up", True),
        ("open safari", False),
        ("remind me in 5 minutes", False),
    ],
)
def test_is_fast_path(query: str, fast: bool) -> None:
    assert is_fast_path(query) is fast


def test_try_fast_path_help() -> None:
    spoken: list[str] = []
    assert try_fast_path("help", speak=spoken.append) is True
    assert spoken[0] == help_text()


def test_try_fast_path_exit_raises() -> None:
    with pytest.raises(JarvisExitRequest):
        try_fast_path("exit", speak=lambda _m: None)
