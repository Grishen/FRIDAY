"""Cross-device sync for Jarvis state (memory, reminders, knowledge index, notes).

Strategy: simple file mirroring to/from a sync directory you control —
typically a cloud-synced folder such as:

- macOS iCloud Drive: ``~/Library/Mobile Documents/com~apple~CloudDocs/Jarvis``
- Dropbox / OneDrive: any folder they sync automatically
- A USB stick or network mount

Set ``JARVIS_SYNC_DIR`` to that folder. Then:

- ``sync_push()``    — copy local files → sync dir (newer-wins)
- ``sync_pull()``    — copy sync dir → local files (newer-wins)
- ``sync_now()``     — bidirectional newer-wins sync
- ``start_auto_sync_thread()`` — periodic background sync

We deliberately avoid heavy deps (no boto3, no rclone): if your sync dir is
on iCloud/Dropbox the OS already handles cloud transport.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent
_DATA = ROOT / "data"
_KNOWLEDGE = ROOT / "knowledge_docs"

# Files/folders to mirror. Folders are recursed entirely.
_SYNC_ITEMS: tuple[Path, ...] = (
    _DATA / "jarvis_memory.sqlite",
    _DATA / "jarvis_reminders.sqlite",
    _DATA / "jarvis_open_loops.sqlite",
    _DATA / "jarvis_threads.sqlite",
    _DATA / "jarvis_actions.sqlite",
    _DATA / "jarvis_active_user.json",
    _DATA / "jarvis_users.json",
    _DATA / "jarvis_persona.json",
    _DATA / "jarvis_voiceprints.json",
    _DATA / "jarvis_faceprints.json",
    _DATA / "jarvis_homekit_scenes.json",
    _DATA / "jarvis_routines.sqlite",
    _DATA / "jarvis_post_meeting.sqlite",
    _DATA / "kb_manifest.json",
    _DATA / "kb_vector_backend.marker",
    _DATA / "jarvis_chroma",
    _KNOWLEDGE / "_voice_notes",
    _KNOWLEDGE / "_ingested_urls",
)

_AUTO_STARTED = threading.Event()
_AUTO_STOP = threading.Event()


def sync_dir() -> Optional[Path]:
    raw = os.environ.get("JARVIS_SYNC_DIR", "").strip()
    if not raw:
        return None
    return Path(os.path.expanduser(raw)).resolve()


def sync_enabled() -> bool:
    return sync_dir() is not None


def _relative_to_root(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return Path(path.name)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _copy_file_safely(src: Path, dst: Path) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False


def _walk_files(item: Path) -> Iterable[Path]:
    if item.is_file():
        yield item
    elif item.is_dir():
        for p in item.rglob("*"):
            if p.is_file():
                yield p


def _sync_pair(local: Path, remote: Path, direction: str) -> tuple[int, int]:
    """direction: 'push' | 'pull' | 'both'. Returns (files_copied, files_skipped)."""
    copied = 0
    skipped = 0
    # Push side: every local file → remote
    if direction in ("push", "both"):
        for src in _walk_files(local):
            rel = src.relative_to(local) if local.is_dir() else Path(src.name)
            dst = (remote / rel) if local.is_dir() else remote
            if not dst.exists() or _mtime(src) > _mtime(dst):
                if _copy_file_safely(src, dst):
                    copied += 1
                else:
                    skipped += 1
    # Pull side: every remote file → local
    if direction in ("pull", "both") and remote.exists():
        for src in _walk_files(remote):
            rel = src.relative_to(remote) if remote.is_dir() else Path(src.name)
            dst = (local / rel) if remote.is_dir() else local
            if not dst.exists() or _mtime(src) > _mtime(dst):
                if _copy_file_safely(src, dst):
                    copied += 1
                else:
                    skipped += 1
    return copied, skipped


def _sync_all(direction: str) -> tuple[int, int]:
    target = sync_dir()
    if target is None:
        return 0, 0
    target.mkdir(parents=True, exist_ok=True)
    total_copied = 0
    total_skipped = 0
    for item in _SYNC_ITEMS:
        rel = _relative_to_root(item)
        remote = target / rel
        if not item.exists() and not remote.exists():
            continue
        if item.is_file() or (not item.exists() and rel.suffix):
            c, s = _sync_pair(item, remote, direction)
        else:
            c, s = _sync_pair(item, remote, direction)
        total_copied += c
        total_skipped += s
    return total_copied, total_skipped


def sync_push() -> str:
    if not sync_enabled():
        return "Sync is disabled. Set JARVIS_SYNC_DIR to a cloud-synced folder."
    c, s = _sync_all("push")
    return f"Pushed {c} files to sync dir (skipped {s})."


def sync_pull() -> str:
    if not sync_enabled():
        return "Sync is disabled. Set JARVIS_SYNC_DIR to a cloud-synced folder."
    c, s = _sync_all("pull")
    return f"Pulled {c} files from sync dir (skipped {s})."


def sync_now() -> str:
    if not sync_enabled():
        return "Sync is disabled. Set JARVIS_SYNC_DIR to a cloud-synced folder."
    c, s = _sync_all("both")
    return f"Bidirectional sync done: copied {c} files (skipped {s})."


def describe_sync_status() -> str:
    target = sync_dir()
    if target is None:
        return "Sync is disabled. Set JARVIS_SYNC_DIR to enable cross-device sync."
    exists = target.exists()
    listing = []
    for item in _SYNC_ITEMS:
        local_present = item.exists()
        remote = target / _relative_to_root(item)
        remote_present = remote.exists()
        listing.append(
            f"{_relative_to_root(item)}: local={'y' if local_present else 'n'} remote={'y' if remote_present else 'n'}"
        )
    return f"Sync dir {target} (exists={exists}). " + "; ".join(listing)


def start_auto_sync_thread(*, interval_seconds: int = 300) -> None:
    """Idempotently start a daemon thread doing periodic bidirectional sync."""
    if _AUTO_STARTED.is_set() or not sync_enabled():
        return
    _AUTO_STARTED.set()
    _AUTO_STOP.clear()
    interval = max(30, int(interval_seconds))

    def _loop() -> None:
        # Pull first so a fresh device gets the latest state, then push edits.
        try:
            _sync_all("pull")
        except Exception:
            pass
        while not _AUTO_STOP.is_set():
            try:
                _sync_all("both")
            except Exception:
                pass
            _AUTO_STOP.wait(interval)

    t = threading.Thread(target=_loop, name="jarvis-sync", daemon=True)
    t.start()


def stop_auto_sync_thread() -> None:
    _AUTO_STOP.set()
    _AUTO_STARTED.clear()


__all__ = [
    "describe_sync_status",
    "start_auto_sync_thread",
    "stop_auto_sync_thread",
    "sync_dir",
    "sync_enabled",
    "sync_now",
    "sync_pull",
    "sync_push",
]
