"""Integration tests for sandboxed filesystem tools."""

from __future__ import annotations

import platform
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import friday_api.services.local_host_handlers as local_handlers

from friday_api.config import get_settings
from friday_api.services.local_host_handlers import (
    tool_local_list_directory,
    tool_local_open_application,
    tool_local_quit_application,
    tool_local_read_file,
    tool_local_write_file,
)


def _mock_proc(code: int, out: str, err: str) -> MagicMock:
    proc = MagicMock()
    proc.returncode = code
    proc.communicate = AsyncMock(return_value=(out.encode(), err.encode()))
    return proc


@pytest.mark.asyncio
async def test_local_list_and_read(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FRIDAY_LOCAL_WORKSPACE", str(tmp_path))
    get_settings.cache_clear()
    uid = uuid.uuid4()
    (tmp_path / "note.txt").write_text("Friday", encoding="utf-8")
    listed = await tool_local_list_directory(".", uid)
    assert listed["ok"] is True
    assert listed["entries"]
    blob = await tool_local_read_file("note.txt", uid)
    assert blob["ok"] is True
    assert blob["content"] == "Friday"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_local_disabled_without_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRIDAY_LOCAL_WORKSPACE", raising=False)
    get_settings.cache_clear()
    uid = uuid.uuid4()
    out = await tool_local_read_file("any.txt", uid)
    assert out["ok"] is False
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_local_open_app_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FRIDAY_LOCAL_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("FRIDAY_OPEN_APP_ALLOWLIST", "Calculator,Safari")
    get_settings.cache_clear()
    uid = uuid.uuid4()
    with patch(
        "friday_api.services.local_host_handlers.asyncio.create_subprocess_exec",
        AsyncMock(return_value=_mock_proc(0, "", "")),
    ):
        result = await tool_local_open_application("Calculator", uid)
    assert result["ok"] is True
    assert result["app"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_local_write_file_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FRIDAY_LOCAL_WORKSPACE", str(tmp_path))
    get_settings.cache_clear()
    uid = uuid.uuid4()
    out = await tool_local_write_file("dir/foo.txt", "hello\n", uid)
    assert out["ok"] is True
    assert (tmp_path / "dir/foo.txt").read_text(encoding="utf-8") == "hello\n"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_local_read_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FRIDAY_LOCAL_WORKSPACE", str(tmp_path))
    get_settings.cache_clear()
    uid = uuid.uuid4()
    out = await tool_local_read_file("missing.bin", uid)
    assert out["ok"] is False
    assert "error" in out
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_local_quit_requires_mac(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FRIDAY_LOCAL_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("FRIDAY_OPEN_APP_ALLOWLIST", "Safari")
    get_settings.cache_clear()
    uid = uuid.uuid4()
    monkeypatch.setattr(local_handlers.platform, "system", lambda: "Linux")
    out = await tool_local_quit_application("Safari", uid)
    assert out["ok"] is False
    assert "macos" in str(out["error"]).lower()


@pytest.mark.asyncio
async def test_local_list_requires_directory(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FRIDAY_LOCAL_WORKSPACE", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "solo.txt").write_text("no", encoding="utf-8")
    uid = uuid.uuid4()
    out = await tool_local_list_directory("solo.txt", uid)
    assert out["ok"] is False
    assert out["error"] == "not_a_directory"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_local_read_rejects_large_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FRIDAY_LOCAL_WORKSPACE", str(tmp_path))
    get_settings.cache_clear()
    uid = uuid.uuid4()
    (tmp_path / "fat.txt").write_bytes(b"x" * 600_000)
    out = await tool_local_read_file("fat.txt", uid)
    assert out["ok"] is False
    assert out.get("error") == "file_too_large"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_local_open_blocked_without_allowlist(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("FRIDAY_LOCAL_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("FRIDAY_OPEN_APP_ALLOWLIST", raising=False)
    get_settings.cache_clear()
    uid = uuid.uuid4()
    out = await tool_local_open_application("Calculator", uid)
    assert out["ok"] is False
    assert "allowlist" in out["error"]
    get_settings.cache_clear()
