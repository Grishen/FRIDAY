# Running Friday / Jarvis on Windows

Cross-platform logic lives in `main.py`, `jarvis_brain.py`, and `jarvis_shell.py`. Use this guide when **Windows is your primary machine**.

## Prerequisites

1. **Python 3.11+** from [python.org](https://www.python.org/downloads/windows/) — enable “Add python.exe to PATH” and optionally “tcl/tk” for Tk.
2. Clone the repo and open **PowerShell** or **cmd** in the project folder.
3. Create a virtual environment (recommended):

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\activate
   pip install --upgrade pip
   pip install -r requirements-core.txt
   ```

   Optional stacks:

   ```powershell
   pip install -r requirements-brain.txt
   pip install -r requirements-rag.txt
   pip install -r requirements-shell.txt
   pip install -r requirements-tts.txt
   ```

   If **PyAudio** fails on Windows, try `pip install pipwin && pipwin install pyaudio` or a wheel from your Python version/architecture.

## Environment

Copy `.env.template` to `.env` in the repo root set:

- `OPENAI_API_KEY` (brain)
- `ELEVENLABS_*` (optional premium TTS)

`.env` is loaded when `python-dotenv` is installed (ElevenLabs path loads it).

Also see **`docs/WINDOWS_ADMIN.md`** before enabling **`JARVIS_WINDOWS_ADMIN_TOOLS=1`** (brain tool **`windows_elevated_shell`** still requires **your UAC consent**).

For sandboxed desktop file operations (open / list / previews / guarded deletes): **`docs/FILE_TOOLS.md`** and **`JARVIS_FILE_TOOLS=1`**.

## Text-to-speech (Windows: online + offline)

Default chain in `main.py` when not forcing local-only speech:

1. **ElevenLabs** (paid / trial) — if `.env` has keys  
2. **Microsoft neural “Edge” voices** (free tier, needs internet): `pip install -r requirements-tts.txt`, env **`JARVIS_EDGE_TTS=1`** and optionally **`JARVIS_EDGE_TTS_VOICE`** (`edge-tts --list-voices`)  
3. **Offline** **`pyttsx3`** Windows **SAPI5** voices — improve quality in Settings → Speech; optional **`JARVIS_PYTTSX3_VOICE_SUBSTRING`**

Playback of MP3 from Edge/ElevenLabs uses **ffplay** (ffmpeg), **pygame**, or macOS **afplay** (`elevenlabs_tts.play_mp3`). Microsoft Edge TTS is subject to their terms — use responsibly for personal projects.

## Microphone / privacy

**Settings → Privacy → Microphone** — allow access for Desktop apps / your Python interpreter.

Run the first session from a terminal so SpeechRecognition errors are visible.

## Launch modes

### Voice only (CLI)

```powershell
python main.py
```

### Fullscreen HUD (recommended “Friday overlay”)

```powershell
python jarvis_shell.py
```

### Useful environment variables (`jarvis_shell.py`)

| Variable | Effect |
|---------|--------|
| `JARVIS_FULLSCREEN` | `1` / `yes` — true fullscreen Tk (default in shell script). |
| `JARVIS_ALWAYS_ON_TOP` | `1` — keep HUD above other windows (nice on Windows). |
| `JARVIS_TRAY` | `1` — system tray icon (needs `requirements-shell.txt`). |
| `JARVIS_START_MINIMIZED` | `1` — start with window hidden (**use with `JARVIS_TRAY=1`**). |
| `JARVIS_ELEVENLABS_ONLY` | Set in `.env`; shell defaults echo this. |

**Keys:** **Esc** — leave fullscreen once, **Esc** again — stop voice and exit HUD. **F11** toggles fullscreen.

### Desktop notifications from the brain

The OpenAI brain can call **`desktop_notify`** (`platform_services.py`). On Windows this uses PowerShell + **NotifyIcon balloon** near the tray (quiet window — no flashing console).

## Login / startup (“runs over my desktop”)

You are **not** replacing Windows; you are **starting the HUD after sign-in**:

1. **Startup folder:** `Win+R` → `shell:startup` → shortcut to:

   `"C:\Path\To\.venv\Scripts\pythonw.exe" "C:\Path\To\Jarvis_Voice_Assistant\jarvis_shell.py"`

   Use **`pythonw.exe`** to avoid an extra console window (errors go to `%TEMP%`/nowhere unless you wrap logging — for debugging prefer `python.exe`).

2. **Task Scheduler** (better control):  
   - Trigger: At log on  
   - Action: Start a program → `pythonw.exe` → arguments `C:\...\jarvis_shell.py` → “Start in” = repo directory.

Test with **`python jarvis_shell.py`** before wiring autostart.

## Frozen bundle (PyInstaller)

A starter spec ships as **`jarvis_shell.spec`** (COLLECT/on‑dir layout).

```powershell
pip install pyinstaller
pyinstaller jarvis_shell.spec
```

Output: `dist\FridayShell\FridayShell.exe` (exe name follows the spec).

**First build often misses hidden imports.** If you bundle RAG/Chroma/sentence‑transformers, expect a **large** folder and rerun with extra `--hidden-import` or hooks after reading the traceback.

Keep **`.env` next to the executable** or set system environment variables — do **not** bake secrets into the spec.

### mic / Tk in frozen builds

- PyAudio and Tk must be bundled; you may need `collect_all` for some wheels.
- If the mic fails in the `.exe`, run from source first to isolate whether the bug is freeze-related.

## Parity with macOS

Same repo; paths use `sys.platform` checks (`main.py`, `jarvis_actions.py`, `platform_services.py`, `jarvis_shell.py`). On Mac, use Login Items instead of Task Scheduler — behavior should match aside from notification backend.
