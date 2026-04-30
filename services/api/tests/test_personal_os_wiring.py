"""Governed sandbox path resolution + streaming provider wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from friday_api.config import Settings
from friday_api.providers.factory import get_chat_provider
from friday_api.providers.mock import MockChatProvider
from friday_api.services.local_tool_inputs import local_tool_inputs
from friday_api.services.local_workspace import normalize_relative, safe_join_workspace


def test_strip_leading_absolute_markers() -> None:
    from friday_api.services.local_workspace import strip_leading_absolute_markers

    assert strip_leading_absolute_markers("/notes/x.txt") == "notes/x.txt"
    assert strip_leading_absolute_markers("") == "."


def test_normalize_relative_collapse_dots() -> None:
    assert normalize_relative("a/../b") == "b"


def test_safe_join_file_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "k.txt").write_text("hello", encoding="utf-8")
    p = safe_join_workspace(root, "k.txt")
    assert p.read_text() == "hello"


def test_safe_join_rejects_parent_escape(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="path_escape|absolute"):
        safe_join_workspace(root, "../secret.txt")


def test_safe_join_rejects_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        safe_join_workspace(Path("/tmp/ws"), "/etc/passwd")


def test_factory_returns_mock_when_no_api_key() -> None:
    s = Settings()
    p = get_chat_provider(s)
    assert isinstance(p, MockChatProvider)


def test_factory_returns_openai_when_key_present() -> None:
    from friday_api.providers.openai_chat import OpenAICompatibleChatProvider

    p = get_chat_provider(Settings(openai_api_key="sk-test-key-example-for-wire-contract-tests-only"))
    assert isinstance(p, OpenAICompatibleChatProvider)


def test_local_tool_inputs_quoted_path() -> None:
    body = local_tool_inputs("local.read_file", 'open file "/docs/readme.txt" please')
    assert body["path"] == "/docs/readme.txt"


def test_local_tool_inputs_open_application_kw() -> None:
    body = local_tool_inputs("local.open_application", "please launch Safari")
    assert body["app"].strip()


def test_local_tool_inputs_list_directory_fallback() -> None:
    assert local_tool_inputs("local.list_directory", "show whats in workspace")["path"] == "."


def test_local_tool_inputs_write_file_quote() -> None:
    w = local_tool_inputs("local.write_file", 'save file "notes/log.txt"')
    assert w["path"] == "notes/log.txt"


@pytest.mark.asyncio
async def test_mock_provider_astream_yields_chunks() -> None:
    p = MockChatProvider()
    assembled: list[str] = []
    async for c in p.astream(messages=[{"role": "user", "content": "hi"}], temperature=0.2):
        assembled.append(c)
    full = "".join(assembled)
    assert full == await p.complete(messages=[{"role": "user", "content": "hi"}])
