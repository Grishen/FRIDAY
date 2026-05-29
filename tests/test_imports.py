import importlib
import sys


CORE_MODULES = [
    "voice_router",
    "reminders",
    "calendar_service",
    "calendar_caldav",
    "dialogue_state",
    "jarvis_brain",
    "jarvis_actions",
    "jarvis_exceptions",
    "routines",
    "briefing",
    "local_llm",
]


def test_core_modules_import(repo_root, monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(repo_root))
    for name in CORE_MODULES:
        mod = importlib.import_module(name)
        assert mod is not None
        if name in sys.modules:
            del sys.modules[name]
