"""Side-effect helpers for Jarvis tools (opened by LLM brain or scripts).

Keeps subprocess / webbrowser / third-party imports here so ``main.py`` stays thin.
Each function returns a short text result for the model (and optional user feedback).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from subprocess import call
from urllib.parse import quote_plus

SITE_ALIASES = {
    "youtube": "https://www.youtube.com/",
    "google": "https://www.google.com/",
    "gmail": "https://mail.google.com/",
    "github": "https://github.com/",
}


def open_website(site: str) -> str:
    s = site.strip().lower()
    url = SITE_ALIASES.get(s)
    if not url:
        if s.startswith("http://") or s.startswith("https://"):
            url = site.strip()
        else:
            return f"Unknown site '{site}'. Use one of: {', '.join(SITE_ALIASES.keys())}."

    import webbrowser

    webbrowser.open(url)
    return f"Opened {s if url != site.strip() else url} in the default browser."


def google_search(query: str) -> str:
    import webbrowser

    q = query.strip()
    if not q:
        return "No search query provided."
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(q)}")
    return f"Opened Google results for: {q}"


def wikipedia_summary(topic: str, *, sentences: int = 3) -> str:
    topic = topic.strip()
    if not topic:
        return "No topic provided."

    try:
        import wikipedia
    except ImportError:
        return "Wikipedia library not installed."

    s = max(1, min(20, int(sentences or 3)))
    try:
        return wikipedia.summary(topic, sentences=s, auto_suggest=True, redirect=True)
    except Exception as exc:  # noqa: BLE001
        # Try to disambiguate or suggest related pages.
        msg = str(exc)
        options: list[str] = []
        try:
            options = list(wikipedia.search(topic, results=5)) or []
        except Exception:
            options = []
        if options:
            return (
                f"Wikipedia could not directly answer ({msg[:120]}). "
                f"Closest topics: {', '.join(options[:5])}."
            )
        return f"Wikipedia lookup failed: {msg}"


def wikipedia_related(topic: str, *, limit: int = 6) -> list[str]:
    topic = (topic or "").strip()
    if not topic:
        return []
    try:
        import wikipedia
    except ImportError:
        return []
    try:
        results = wikipedia.search(topic, results=max(1, min(15, limit)))
        return [str(r) for r in results]
    except Exception:
        return []


def current_time_display() -> str:
    import datetime

    time_str = datetime.datetime.now().strftime("%I:%M %p")
    return f"The current local time is {time_str}."


def current_date_display() -> str:
    import datetime

    today = datetime.date.today()
    return f"Today's date is {today.strftime('%B %d, %Y')}."


def play_youtube_music(query: str) -> str:
    import pywhatkit

    q = query.strip()
    if not q:
        return "Say what song or topic to play."
    pywhatkit.playonyt(q)
    return f"Started YouTube playback for: {q}"


def open_application(application: str) -> str:
    app = application.strip().lower()
    msg = ""

    if app in ("notepad", "text editor", "textedit"):
        msg = "Opening text editor."
        if sys.platform == "win32":
            os.startfile(r"C:\WINDOWS\system32\notepad.exe")  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "TextEdit"], check=False)
        elif shutil.which("gedit"):
            subprocess.run(["gedit"], check=False)
        elif shutil.which("mousepad"):
            subprocess.run(["mousepad"], check=False)

    elif app in ("terminal", "command prompt", "cmd"):
        msg = "Opening terminal."
        if sys.platform == "win32":
            os.system("start cmd")
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Terminal"], check=False)
        else:
            for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "kitty"):
                if shutil.which(term):
                    subprocess.run([term], check=False)
                    break

    elif app in ("vscode", "code", "visual studio code"):
        msg = "Opening Visual Studio Code."
        if sys.platform == "win32":
            code_path = os.path.expanduser(
                r"~\AppData\Local\Programs\Microsoft VS Code\Code.exe"
            )
            if os.path.isfile(code_path):
                os.startfile(code_path)  # type: ignore[attr-defined]
            else:
                os.startfile("code")  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Visual Studio Code"], check=False)
        elif shutil.which("code"):
            subprocess.run(["code"], check=False)

    elif app in ("calculator", "calc"):
        msg = "Opening calculator."
        if sys.platform == "win32":
            call(["calc.exe"])
        elif sys.platform == "darwin":
            subprocess.run(["open", "-a", "Calculator"], check=False)
        elif shutil.which("gnome-calculator"):
            subprocess.run(["gnome-calculator"], check=False)

    else:
        return f"Unsupported application shortcut: '{application}'. Try notepad, terminal, vscode, or calculator."

    return msg


def open_application_by_name(application: str) -> str:
    """Try macOS ``open -a`` for arbitrary app names; else use known shortcuts."""
    name = (application or "").strip()
    if not name:
        return "Which application should I open?"
    if sys.platform == "darwin":
        last_err = ""
        for candidate in (name, name.title(), name.capitalize()):
            res = subprocess.run(["open", "-a", candidate], capture_output=True, text=True)
            if res.returncode == 0:
                return f"Opening {candidate}."
            last_err = (res.stderr or res.stdout or "").strip()
        suffix = f" {last_err[:80]}" if last_err else ""
        return f"Could not open '{name}'.{suffix}"
    return open_application(name)


def volume_action(action: str) -> str:
    import pyautogui

    a = action.strip().lower()
    if a in ("up", "increase"):
        pyautogui.press("volumeup")
        return "Pressed volume up."
    if a in ("down", "decrease"):
        pyautogui.press("volumedown")
        return "Pressed volume down."
    if a in ("mute", "toggle mute"):
        pyautogui.press("volumemute")
        return "Muted or toggled mute."
    return f"Unknown volume action: '{action}'. Use up, down, or mute."


def check_internet() -> str:

    try:
        import urllib.request

        urllib.request.urlopen("https://www.google.com/", timeout=5)
        return "Internet connection appears available."
    except OSError:
        return "Internet connection appears unavailable."


def measure_internet_speed() -> str:
    try:
        import speedtest
    except ImportError:
        return "speedtest-cli is not installed."

    try:
        st = speedtest.Speedtest()
        dl = round(float(st.download() / 1e6))
        ul = round(float(st.upload() / 1e6))
        return f"Approximate speeds: download {dl} Mb/s, upload {ul} Mb/s."
    except Exception as exc:  # noqa: BLE001
        return f"Speed test failed: {exc}"


def tell_joke() -> str:

    try:
        import pyjokes

        return pyjokes.get_joke()
    except Exception as exc:  # noqa: BLE001
        return f"Could not fetch a joke: {exc}"


def windows_request_elevated_shell(shell: str = "powershell") -> str:
    """Open a **new** elevated Windows shell via UAC (User must click Yes).

    This does **not** grant the assistant silent admin rights — it launches the
    Microsoft shell you choose behind a consent dialog.

    **Disabled** unless ``JARVIS_WINDOWS_ADMIN_TOOLS=1`` — see docs/WINDOWS_ADMIN.md .
    """
    if sys.platform != "win32":
        return "Elevated Windows shells are Windows-only."

    flag = os.environ.get("JARVIS_WINDOWS_ADMIN_TOOLS", "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return (
            "Elevated admin shell is disabled. Set JARVIS_WINDOWS_ADMIN_TOOLS=1 in .env, "
            "then approve the Windows UAC dialog when prompted. "
            "Read docs/WINDOWS_ADMIN.md for risks."
        )

    kind = (shell or "powershell").strip().lower()
    if kind == "cmd":
        inner = "Start-Process -FilePath cmd.exe -Verb RunAs"
    elif kind == "powershell":
        inner = "Start-Process -FilePath powershell.exe -Verb RunAs"
    else:
        return "Unknown shell. Use powershell or cmd."

    try:
        # Visible window — user must approve UAC and then type privileged commands manually.
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Normal",
                "-Command",
                inner,
            ],
            close_fds=True,
        )
        return (
            "Launched elevated shell request — check for a blue Windows UAC prompt. "
            f"Approve to open elevated {kind}."
        )
    except Exception as exc:  # noqa: BLE001
        return f"Could not start elevated shell: {exc}"
