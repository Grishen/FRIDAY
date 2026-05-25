"""Fullscreen FRIDAY/JARVIS shell — voice-first desktop overlay.

Run from the repo root::

    python jarvis_shell.py

See ``docs/WINDOWS.md`` for Task Scheduler autostart & PyInstaller.

Env (high level):

- ``JARVIS_FULLSCREEN`` — default ``1``: Tk fullscreen where supported.
- ``JARVIS_ALWAYS_ON_TOP`` — ``1`` keeps HUD above other windows (strong on Windows).
- ``JARVIS_TRAY`` — ``1`` + ``pip install -r requirements-shell.txt`` for a tray icon.
- ``JARVIS_START_MINIMIZED`` — ``1`` hides the HUD at launch (pair with ``JARVIS_TRAY``).
- ``JARVIS_ELEVENLABS_ONLY`` — shell sets default ``1``; override with ``0`` for pyttsx3 fallback.

Keys: **Esc** — exit fullscreen first, then end session. **F11** toggles fullscreen.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from typing import Any

# Apply before importing main so speak() picks up preferences.
os.environ.setdefault("JARVIS_ELEVENLABS_ONLY", "1")
os.environ.setdefault("JARVIS_FULLSCREEN", "1")

tk: Any = None
tkfont: Any = None
_TKIMPORT_ERROR: ImportError | None = None
try:
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError as err:
    _TKIMPORT_ERROR = err

import main as jarvis_main

if not jarvis_main.elevenlabs_tts.is_configured():
    print(
        "WARNING: ElevenLabs API keys are missing (.env next to project root). "
        "With JARVIS_ELEVENLABS_ONLY=1 you may get no spoken output.",
        file=sys.stderr,
    )


def _env_yes(key: str, *, default: str = "0") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")


def _apply_fullscreen(root: Any) -> None:
    want = _env_yes("JARVIS_FULLSCREEN", default="1")
    if not want:
        return
    try:
        root.attributes("-fullscreen", True)
    except tk.TclError:
        if sys.platform == "win32":
            try:
                root.state("zoomed")
            except tk.TclError:
                pass


def _apply_always_on_top(root: Any) -> None:
    if not _env_yes("JARVIS_ALWAYS_ON_TOP"):
        return
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass


def _maybe_start_tray(
    root: Any,
    *,
    stop_voice: threading.Event,
    request_stop: Any,
    title: str = "Friday",
) -> Any:
    if not _env_yes("JARVIS_TRAY"):
        return None
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print(
            "JARVIS_TRAY=1 but pystray/Pillow missing — run: pip install -r requirements-shell.txt",
            file=sys.stderr,
        )
        return None

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(71, 192, 255, 255))

    def show_hud(icon: Any, item: Any = None) -> None:
        del icon, item  # pystray callback signature

        def _lift() -> None:
            root.deiconify()
            root.lift()
            root.focus_force()
            try:
                root.attributes("-topmost", True)
                root.after(400, lambda: root.attributes("-topmost", False))
            except tk.TclError:
                pass

        root.after(0, _lift)

    def quit_app(icon: Any, item: Any = None) -> None:
        del item  # unused
        request_stop()
        try:
            icon.stop()
        except Exception:
            pass
        root.after(0, root.quit)

    menu = pystray.Menu(
        pystray.MenuItem("Show HUD", show_hud),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("jarvis_voice", img, title, menu)

    threading.Thread(target=icon.run, daemon=True).start()
    return icon


def launch() -> int:
    if tk is None or tkfont is None:
        print(
            "Tkinter isn't available (_tkinter missing). Your Python build has no Tk.\n\n"
            "  • Fallback: voice session runs in this terminal (same as: python main.py).\n\n"
            "  • Fix on macOS + pyenv: install Tcl/Tk and reinstall Python linked to it, e.g.:\n"
            "       brew install tcl-tk\n"
            "       # see: https://github.com/pyenv/pyenv/wiki/Common-build-problems\n\n"
            "    Or use Python from python.org or `brew install python-tk`.\n\n"
            "  • Windows: reinstall Python from python.org with Tcl/Tk included.",
            file=sys.stderr,
        )
        print("Import error:", _TKIMPORT_ERROR, file=sys.stderr)
        jarvis_main.run_voice_session()
        return 0

    ui_updates: queue.Queue[tuple[str, str]] = queue.Queue()
    stop_voice = threading.Event()

    root = tk.Tk()
    root.title("Friday / J.A.R.V.I.S.")
    root.configure(background="#070b10")

    root.update_idletasks()

    fullscreen_wanted = _env_yes("JARVIS_FULLSCREEN", default="1")
    if fullscreen_wanted:
        _apply_fullscreen(root)

    _apply_always_on_top(root)

    mono = "Menlo" if sys.platform == "darwin" else "Consolas"
    hud = tkfont.Font(family=mono, size=16)
    hud_small = tkfont.Font(family=mono, size=12)

    status_var = tk.StringVar(value="Starting systems…")
    heard_var = tk.StringVar(value="Awaiting vocal interface.")

    frame = tk.Frame(root, bg="#070b10", padx=32, pady=32)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frame,
        text="J.A.R.V.I.S.",
        fg="#47c0ff",
        bg="#070b10",
        font=(mono, 28, "bold"),
    ).pack(anchor="w")

    tk.Label(
        frame,
        textvariable=status_var,
        fg="#8899aa",
        bg="#070b10",
        font=hud_small,
        wraplength=900,
        justify=tk.LEFT,
    ).pack(anchor="w", pady=(8, 24))

    tk.Label(frame, text="Last heard", fg="#47c0ff", bg="#070b10", font=hud_small).pack(anchor="w")

    tk.Label(
        frame,
        textvariable=heard_var,
        fg="#d0dce8",
        bg="#070b10",
        font=hud,
        wraplength=900,
        justify=tk.LEFT,
    ).pack(anchor="w", pady=(4, 24))

    hint_os = (
        "Esc — leave fullscreen · Esc again — quit · F11 — toggle fullscreen · "
        "Tray: pip install pystray pillow + set JARVIS_TRAY=1"
        if sys.platform == "win32"
        else "Esc — leave fullscreen · Esc again — quit · F11 — toggle fullscreen"
    )

    tk.Label(
        frame,
        text=hint_os + ". Your desktop stays underneath this HUD.",
        fg="#556677",
        bg="#070b10",
        font=hud_small,
        wraplength=900,
        justify=tk.LEFT,
    ).pack(side=tk.BOTTOM, anchor="w", pady=16)

    btn_row = tk.Frame(frame, bg="#070b10")
    btn_row.pack(side=tk.BOTTOM, anchor="e")

    def request_stop() -> None:
        status_var.set("Stopping voice session…")
        stop_voice.set()

    def toggle_fullscreen() -> None:
        try:
            cur = root.attributes("-fullscreen")
        except tk.TclError:
            if sys.platform == "win32":
                try:
                    st = root.state()
                    root.state("" if st == "zoomed" else "zoomed")
                except tk.TclError:
                    pass
            return
        try:
            root.attributes("-fullscreen", not cur)
        except tk.TclError:
            if sys.platform == "win32" and not cur:
                try:
                    root.state("zoomed")
                except tk.TclError:
                    pass

    def on_escape(_event=None) -> None:
        try:
            if root.attributes("-fullscreen"):
                root.attributes("-fullscreen", False)
                return
        except tk.TclError:
            pass
        if sys.platform == "win32":
            try:
                if root.state() == "zoomed":
                    root.state("normal")
                    return
            except tk.TclError:
                pass
        request_stop()

    tk.Button(
        btn_row,
        text="Fullscreen",
        command=toggle_fullscreen,
        fg="#070b10",
        bg="#47c0ff",
        activebackground="#6ad0ff",
        font=hud_small,
    ).pack(side=tk.RIGHT, padx=(8, 0))

    tk.Button(
        btn_row,
        text="Quit shell",
        command=request_stop,
        fg="#070b10",
        bg="#8899aa",
        activebackground="#aab",
        font=hud_small,
    ).pack(side=tk.RIGHT)

    tray_icon = _maybe_start_tray(
        root, stop_voice=stop_voice, request_stop=request_stop, title=os.environ.get("JARVIS_TRAY_TITLE", "Friday")
    )

    root.protocol("WM_DELETE_WINDOW", request_stop)
    root.bind("<Escape>", on_escape)
    root.bind("<F11>", lambda _e=None: toggle_fullscreen())

    if _env_yes("JARVIS_START_MINIMIZED"):
        if tray_icon is None:
            print(
                "JARVIS_START_MINIMIZED=1 without tray — window will iconify to taskbar only.",
                file=sys.stderr,
            )
            root.iconify()
        else:
            root.withdraw()

    def apply_updates() -> None:
        try:
            while True:
                kind, payload = ui_updates.get_nowait()
                if kind == "status":
                    status_var.set(payload)
                elif kind == "heard":
                    heard_var.set(payload)
                elif kind == "log":
                    print(payload, flush=True)
        except queue.Empty:
            pass
        root.after(100, apply_updates)

    def voice_worker() -> None:
        def on_listen() -> None:
            ui_updates.put(("status", "Listening…"))

        def on_heard(text: str) -> None:
            ui_updates.put(("heard", text))
            ui_updates.put(("status", "Processing command…"))

        try:
            jarvis_main.run_voice_session(
                do_greet=True,
                stop_event=stop_voice,
                on_listening=on_listen,
                on_heard=on_heard,
            )
        except Exception:
            ui_updates.put(("status", "Voice core crashed — see terminal."))
            ui_updates.put(("log", traceback.format_exc()))
        finally:
            root.after(0, root.quit)

    threading.Thread(target=voice_worker, daemon=True).start()
    apply_updates()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(launch())
