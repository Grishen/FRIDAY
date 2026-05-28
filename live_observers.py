"""Live camera + live screen daemons.

Both observers run on their own thread and surface signal only when something
*meaningful* happens. They are conservative by default to avoid being creepy
or noisy.

LiveCameraObserver
------------------
- Captures a frame every ``camera_period_s`` seconds (default 60).
- Diffs against the previous frame: if pixel-difference is below
  ``camera_change_thresh``, nothing happens (you're stationary at the desk).
- When motion crosses the threshold *and* you've been at the desk a long
  time, fires "you've been here X minutes" suggestions.
- When the user said "watch me" recently, fires immediate descriptions of
  significant changes ("you stood up", "someone joined").

LiveScreenObserver
------------------
- Captures every ``screen_period_s`` seconds (default 90).
- Diffs the structured analysis of the current screenshot (UI mode) against
  the previous. Surfaces help only when:
    * The same error dialog has persisted for 2+ checks
    * The user has been on the same screen for a long time with no input
    * The UI shows known-stuck states (e.g. spinner, blank field with cursor)
- Otherwise stays completely silent.

Both can be toggled on/off independently via ``start()``/``stop()``.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


def _env_float(k: str, default: float) -> float:
    try:
        return float(os.environ.get(k, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(k: str, default: int) -> int:
    try:
        return int(os.environ.get(k, str(default)))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Image diff helper
# --------------------------------------------------------------------------- #


def _image_change_score(path_a: str, path_b: str, *, max_dim: int = 240) -> float:
    """Return 0..1 dissimilarity score between two images using thumbnail RMS diff."""
    try:
        from PIL import Image  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return 0.0
    try:
        a = Image.open(path_a).convert("RGB")
        b = Image.open(path_b).convert("RGB")
    except Exception:
        return 0.0
    a.thumbnail((max_dim, max_dim))
    b.thumbnail((max_dim, max_dim))
    if a.size != b.size:
        b = b.resize(a.size)
    arr_a = np.asarray(a, dtype="float32")
    arr_b = np.asarray(b, dtype="float32")
    diff = np.abs(arr_a - arr_b)
    return float(diff.mean()) / 255.0


# --------------------------------------------------------------------------- #
# Camera observer
# --------------------------------------------------------------------------- #


@dataclass
class _CameraState:
    last_path: str = ""
    last_motion_at: float = 0.0
    seated_since: float = field(default_factory=time.time)
    last_alert_at: float = 0.0


class LiveCameraObserver:
    def __init__(self, on_event: Optional[Callable[[str], None]] = None):
        self.on_event = on_event
        self.period_s = _env_float("JARVIS_LIVE_CAMERA_PERIOD_S", 60.0)
        self.change_thresh = _env_float("JARVIS_LIVE_CAMERA_CHANGE", 0.05)
        self.seated_warn_min = _env_float("JARVIS_LIVE_CAMERA_SEATED_WARN_MIN", 90.0)
        self.alert_cooldown_s = _env_float("JARVIS_LIVE_CAMERA_COOLDOWN_S", 1800.0)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = _CameraState()

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="live-camera-observer", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.0)
        self._thread = None

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._pause.is_set():
                self._stop.wait(self.period_s)
                continue
            try:
                self._tick()
            except Exception:
                pass
            self._stop.wait(self.period_s)

    def _tick(self) -> None:
        try:
            from vision import capture_webcam
        except Exception:
            return
        ok, path = capture_webcam()
        if not ok:
            return

        now = time.time()
        if self._state.last_path:
            change = _image_change_score(self._state.last_path, path)
            if change >= self.change_thresh:
                self._state.last_motion_at = now
                # Significant motion — reset seated timer.
                self._state.seated_since = now

        # Seated-too-long alert.
        seated_min = (now - self._state.seated_since) / 60.0
        if (seated_min >= self.seated_warn_min and
                (now - self._state.last_alert_at) >= self.alert_cooldown_s):
            self._state.last_alert_at = now
            if self.on_event:
                try:
                    self.on_event(
                        f"You've been at the desk for about {int(seated_min)} minutes — "
                        "want a stretch reminder?"
                    )
                except Exception:
                    pass

        # Replace the previous reference frame.
        prev = self._state.last_path
        self._state.last_path = path
        if prev and prev != path:
            try:
                os.unlink(prev)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Screen observer
# --------------------------------------------------------------------------- #


@dataclass
class _ScreenState:
    last_path: str = ""
    last_summary: str = ""
    same_screen_since: float = field(default_factory=time.time)
    last_alert_at: float = 0.0
    last_error_seen: str = ""
    error_streak: int = 0


_STUCK_HINTS = ("error", "failed", "exception", "spinner", "loading", "frozen", "stuck")


class LiveScreenObserver:
    def __init__(self, on_event: Optional[Callable[[str], None]] = None):
        self.on_event = on_event
        self.period_s = _env_float("JARVIS_LIVE_SCREEN_PERIOD_S", 90.0)
        self.change_thresh = _env_float("JARVIS_LIVE_SCREEN_CHANGE", 0.02)
        self.stuck_min = _env_float("JARVIS_LIVE_SCREEN_STUCK_MIN", 6.0)
        self.alert_cooldown_s = _env_float("JARVIS_LIVE_SCREEN_COOLDOWN_S", 600.0)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = _ScreenState()

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="live-screen-observer", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.0)
        self._thread = None

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._pause.is_set():
                self._stop.wait(self.period_s)
                continue
            try:
                self._tick()
            except Exception:
                pass
            self._stop.wait(self.period_s)

    def _tick(self) -> None:
        try:
            from vision import take_screenshot, analyze_image
        except Exception:
            return
        ok, path = take_screenshot()
        if not ok:
            return

        now = time.time()
        change = 1.0
        if self._state.last_path:
            change = _image_change_score(self._state.last_path, path)
        if change < self.change_thresh:
            # Same screen as before.
            same_min = (now - self._state.same_screen_since) / 60.0
            if (same_min >= self.stuck_min and
                    (now - self._state.last_alert_at) >= self.alert_cooldown_s):
                # Do a quick UI-mode analysis to confirm a stuck state.
                res = analyze_image(path, mode="ui")
                data = res.get("json") if isinstance(res, dict) else None
                if isinstance(data, dict):
                    errors = data.get("errors") or []
                    if errors:
                        first = str(errors[0])
                        if first != self._state.last_error_seen:
                            self._state.last_error_seen = first
                            self._state.error_streak = 1
                        else:
                            self._state.error_streak += 1
                        if self._state.error_streak >= 2 and self.on_event:
                            self._state.last_alert_at = now
                            try:
                                self.on_event(
                                    f"I see an error on your screen: '{first}'. Want me to help with it?"
                                )
                            except Exception:
                                pass
                            self._state.error_streak = 0
        else:
            self._state.same_screen_since = now
            self._state.error_streak = 0
            self._state.last_error_seen = ""

        prev = self._state.last_path
        self._state.last_path = path
        if prev and prev != path:
            try:
                os.unlink(prev)
            except OSError:
                pass


__all__ = ["LiveCameraObserver", "LiveScreenObserver"]
