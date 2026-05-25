# Windows “admin access” — what’s possible vs what’s reckless

Film FRIDAY can **silently run anything**. Real Windows separates **Administrator** privileges from normal apps deliberately. This project **never** hides an API that lets an LLM run **arbitrary** commands **without** your explicit operating-system consent, because speech + cloud models create **instant catastrophic risk** (audio injection, phishing, ransomware, wiping disks).

Below is how to work **safely** while still controlling your machine powerfully.

---

## What you probably want

1. **You** approve Windows **UAC** when something sensitive happens.
2. The assistant performs **narrow, reviewed automations** (open apps, search, browsers, reminders, scripted tools you ship).
3. Optional: you run Friday **elevated yourself** only when debugging something that genuinely needs admin for every subprocess.

---

## Option A — “Full admin-ish” behaviour (elevate the assistant process)

Anything the Python process launches **inherits its token**:

1. Quit Friday / Jarvis.
2. Locate `python.exe` or your built `FridayShell.exe`.
3. **Right‑click → Run as administrator** (or Task Scheduler checkbox “Run with highest privileges” for that task only).

**Pros:** Scheduled tasks / installers / registry edits invoked from your tooling may succeed without repeatedly spawning UAC.

**Cons:** If the assistant or any dependency misbehaved, harm runs **elevated**. This is precisely why “run assistant as SYSTEM always” is a bad default.

---

## Option B — UAC-gated elevated shell (`windows_elevated_shell` brain tool)

This repo exposes one **narrow** privilege surface:

Set in `.env`:

```env
JARVIS_WINDOWS_ADMIN_TOOLS=1
```

Then the OpenAI brain can call **`windows_elevated_shell`** with `shell`: **`powershell`** or **`cmd`**.

What it does behind the curtains:

```powershell
Start-Process powershell.exe -Verb RunAs
# or cmd.exe RunAs equivalent
```

**You still get Windows’ consent dialog.** This simply saves you navigating Start Menu yourself. Commands after that window opens are typed **by you** (Friday does not magically receive an admin pipe).

If `JARVIS_WINDOWS_ADMIN_TOOLS` is unset/off, attempts return `"disabled"` text.

---

## What we consciously do **NOT** automate

These would be irresponsible as generic LLM tools:

| Capability | Reason |
|-----------|--------|
| Run arbitrary `{text}` elevated | Prompt/voice spoofing ⇒ instant remote code execution-as-admin |
| Persistently disable Defender / firewall | Abuse magnet |
| Silently elevate without UAC bypass | Contradicts Windows security model |

If you genuinely need scripted admin maintenance, ship **explicit** `.ps1` files you wrote and **sign** them, invoke them deliberately (still with review), outside the conversational agent.

---

## Hardening checklist

| Step | Recommendation |
|------|----------------|
| Separate accounts | Use a Standard user account daily; escalate only intentionally |
| Webcam / microphone | Disable hot-mic persistence when unattended |
| API keys | Keep `.env` off cloud sync; revoke keys if leaked |
| Strong model | Larger models hallucinate confidently — double-check destructive instructions |
| Backups | File History / snapshots before bulk automation experiments |

---

## macOS analogue

Privileged work goes through **`sudo`** / **`osascript` + admin password** dialogs. Mirror the discipline: elevate **process** when needed rather than punching silent root holes via chat.
