import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep tests from writing into the real data/ folder."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("JARVIS_DATA_DIR", str(data))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("JARVIS_LOCAL_LLM", "0")
    monkeypatch.setenv("JARVIS_BRAIN", "0")
    try:
        from routines import _ensure_schema as ensure_routines_schema

        ensure_routines_schema()
    except Exception:
        pass
    return data


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
