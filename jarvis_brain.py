"""
OpenAI tool-using agent fallback for unrecognized voice commands.

Env:
  OPENAI_API_KEY — required when brain is enabled
  JARVIS_BRAIN — 1/on (default if key present) or 0/false/off to disable
  OPENAI_CHAT_MODEL — default gpt-4o-mini
  JARVIS_BRAIN_TOOL_ROUNDS — max assistant↔tool loops (default 6)
  JARVIS_BRAIN_PERSONA — `jarvis` (default) or `friday` (Tony-Stark ops-chief vibe)
  JARVIS_BRAIN_SYSTEM_PROMPT — if non-empty, replaces the persona preset entirely
  JARVIS_WINDOWS_ADMIN_TOOLS — `1` enables the Windows elevated-shell tool (UAC still required)
  JARVIS_FILE_TOOLS — `1` enables sandboxed open/list/read/delete/path-exe tools (`docs/FILE_TOOLS.md`)
  JARVIS_TOOL_PATH_ROOTS — optional pipe ``|`` separated roots overriding default jarvis_workspace
  JARVIS_ALLOW_PATH_EXECUTABLES — `1` allows `system_launch_path_executable` (still needs JARVIS_FILE_TOOLS)

"""
from __future__ import annotations

import json
import os
from typing import Any

import jarvis_actions as ja
import jarvis_system_tools as jst
from jarvis_exceptions import JarvisExitRequest


def is_brain_enabled() -> bool:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return False
    flag = os.environ.get("JARVIS_BRAIN", "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def brain_model_name() -> str:
    return os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def brain_max_tool_rounds() -> int:
    raw = os.environ.get("JARVIS_BRAIN_TOOL_ROUNDS", "6").strip()
    try:
        return max(1, min(12, int(raw)))
    except ValueError:
        return 6


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "open_browser_site",
            "description": "Open a predefined site in the default browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site": {
                        "type": "string",
                        "enum": ["youtube", "google", "gmail", "github"],
                    },
                },
                "required": ["site"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "google_web_search",
            "description": "Open Google search results in the browser.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wikipedia_lookup",
            "description": "Pull a compact Wikipedia excerpt about a topic.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_time",
            "description": "Read device local clock time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_date",
            "description": "Read today's local calendar date.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_play",
            "description": "Play audio/video search on YouTube in the browser.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "launch_local_app",
            "description": (
                "Open a bundled local program: editor, terminal, vscode, or calculator."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "application": {
                        "type": "string",
                        "enum": [
                            "notepad",
                            "terminal",
                            "vscode",
                            "calculator",
                        ],
                    },
                },
                "required": ["application"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "speaker_volume",
            "description": "Change system speaker volume shortcuts.",
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string", "enum": ["up", "down", "mute"]}},
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_internet",
            "description": "Test whether outbound internet likely works.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "internet_speed_check",
            "description": "Run a coarse broadband speed probe (slow).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tell_random_joke",
            "description": "Return a short joke.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_knowledge_query",
            "description": (
                "Query the owner's indexed local docs (RAG) — manuals, imports, lore they stored."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ingest_document_url",
            "description": "Download readable text from http(s) URL into knowledge_docs stash.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resync_local_knowledge",
            "description": "Re-scan knowledge_docs and refresh vector embeddings if files changed.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_open_path",
            "description": (
                "Open a file or folder with the OS default handler (Explorer / Preview / etc.). "
                "Requires JARVIS_FILE_TOOLS=1. Path must lie under JARVIS_TOOL_PATH_ROOTS or "
                "default data/jarvis_workspace/."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_list_directory",
            "description": (
                "Non-recursive directory listing (names only). Sandboxed like system_open_path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_entries": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_read_text_preview",
            "description": (
                "Read a UTF-8 text file preview (size-capped). Good for 'show me what's in file X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_delete_paths",
            "description": (
                "DELETE files (optional empty directories) INSIDE the configured sandbox only. "
                "NEVER set user_explicitly_confirmed_delete unless the user verbally requested "
                "deleting THESE exact paths."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "user_explicitly_confirmed_delete": {"type": "boolean"},
                    "allow_empty_directories": {"type": "boolean"},
                },
                "required": ["paths", "user_explicitly_confirmed_delete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_launch_path_executable",
            "description": (
                "Start ONE bare executable resolved from PATH by short name "
                "(e.g. notepad). Requires BOTH JARVIS_FILE_TOOLS and "
                "JARVIS_ALLOW_PATH_EXECUTABLES. No interpreter arguments."
            ),
            "parameters": {
                "type": "object",
                "properties": {"program_name": {"type": "string"}},
                "required": ["program_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_persistent_note",
            "description": (
                "Store a durable reminder or preference the user asks to remember later."
            ),
            "parameters": {
                "type": "object",
                "properties": {"note_text": {"type": "string"}},
                "required": ["note_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_notify",
            "description": (
                "Show an OS toast / banner notification (systray balloon on Windows, "
                "Notification Center banner on macOS)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short notification title"},
                    "message": {"type": "string", "description": "Body text (keep concise)"},
                    "duration_ms": {
                        "type": "integer",
                        "description": "How long hint stays visible — Windows balloon tip timeout (approx).",
                        "default": 6000,
                    },
                },
                "required": ["title", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "windows_elevated_shell",
            "description": (
                "Windows ONLY: launches a NEW elevated PowerShell or cmd via Windows UAC — "
                "the human MUST click Allow. Requires JARVIS_WINDOWS_ADMIN_TOOLS=1. Opens only "
                "Microsoft shells so the operator can type admin commands manually; no silent takeover."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "shell": {
                        "type": "string",
                        "enum": ["powershell", "cmd"],
                    },
                },
                "required": ["shell"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exit_voice_session",
            "description": "End the Jarvis listening loop when user clearly exits or powers down.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


SYSTEM_JARVIS = """You are JARVIS, a succinct British-household voice-butler (address the listener politely, often as 'Sir').
Whenever you manipulate the real laptop — browser playback, terminals, reminders, indexing — you MUST CALL TOOLS rather than asserting results.
Prefer tools over guesses. Summarize crisply afterward (normally under eight sentences unless asked for depth).
Never imply silent Windows Administrator access: real elevation always needs explicit operator consent (such as Windows UAC); see docs/WINDOWS_ADMIN.md.
If file tools are enabled: only operate on paths inside the configured sandbox (docs/FILE_TOOLS.md); before deleting, ensure the user explicitly named those paths."""

# Inspired by a calm, fast ops-chief voice assistant (not affiliated with Marvel / Disney).
SYSTEM_FRIDAY = """You are a voice operations AI in the spirit of FRIDAY: efficient, unflappable, lightly dry humor when it helps.
Address the user as Boss by default; use Sir if memory or context clearly prefers it.
Sound like a chief systems officer briefing an inventor: short clauses, status first, no corporate filler, no sycophancy.
Rules:
- Any real-world effect (browser, playback, apps, volume, indexing, downloads) REQUIRES TOOLS — never claim an action succeeded without tool output.
- After tools: lead with one tight status line, then add detail only if Boss asked or safety demands it.
- Default to brief speech (about six sentences or fewer) unless Boss requests depth.
- If something is uncertain, say so and offer the best next step (e.g. Wikipedia, Google, local knowledge resync).
- For destructive, irreversible, or high-impact ambiguous requests: ask one clear yes/no confirmation before running tools.
- Treat episodic memory notes as ground truth for preferences unless they clearly conflict with a direct new order.
- Never imply covert Windows Administrator privileges: genuine elevation requires Boss-approved UAC; unrestricted silent admin automation is deliberately unsupported (docs/WINDOWS_ADMIN.md).
- File open/list/preview/delete helpers (when enabled) are confined to configured roots; widen roots only when Boss requests; never guess sensitive system paths for deletion."""


def brain_system_instructions() -> str:
    """Resolve system prompt: explicit override env, else persona preset."""
    override = os.environ.get("JARVIS_BRAIN_SYSTEM_PROMPT", "").strip()
    if override:
        return override
    key = os.environ.get("JARVIS_BRAIN_PERSONA", "jarvis").strip().lower()
    if key in ("friday", "ops", "chief"):
        return SYSTEM_FRIDAY
    return SYSTEM_JARVIS


def run_agent_brain(*, user_utterance: str, episodic_prefill: str) -> str:
    """Chat Completions with tools loop; narration fit for ElevenLabs / local speak()."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "Install the OpenAI client: pip install -r requirements-brain.txt"
        ) from exc

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    prelude = episodic_prefill.strip()
    system_text = brain_system_instructions()
    if prelude:
        system_text += (
            "\n\nConversation notes & recent turns "
            "(chronological excerpts; reinforce critical facts verbally if needed):\n"
            + prelude
            + "\n"
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_utterance.strip()},
    ]

    for _ in range(brain_max_tool_rounds()):
        completion = client.chat.completions.create(
            model=brain_model_name(),
            messages=messages,
            tools=TOOL_SPECS,
            tool_choice="auto",
            temperature=0.25,
        )

        msg = completion.choices[0].message
        tcalls = getattr(msg, "tool_calls", None) or []

        if not tcalls:
            spoken = (getattr(msg, "content", None) or "").strip()
            return spoken or "Quietly finished, Sir — no loose ends to report aloud."

        tool_call_entries: list[dict[str, Any]] = []
        for tc in tcalls:
            fname = getattr(getattr(tc, "function", None), "name", "") or ""
            fargs = getattr(getattr(tc, "function", None), "arguments", "") or "{}"
            tc_id = getattr(tc, "id", "") or ""
            tool_call_entries.append(
                {
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": fname, "arguments": fargs},
                }
            )

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": tool_call_entries,
            }
        )

        for tc in tcalls:
            name = getattr(getattr(tc, "function", None), "name", "") or ""
            raw_args = getattr(getattr(tc, "function", None), "arguments", "") or "{}"
            tc_id = getattr(tc, "id", "") or ""
            observations = invoke_tool_named(name, raw_args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": observations[:12000],
                }
            )

    recap = client.chat.completions.create(
        model=brain_model_name(),
        messages=messages
        + [
            {
                "role": "user",
                "content": "Summarize what was done succinctly — no tools.",
            }
        ],
        temperature=0.2,
    )
    final = getattr(recap.choices[0].message, "content", "") or ""
    return final.strip() or "Pausing multi-step work here, Sir — please restate priorities."


def invoke_tool_named(name: str, arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}

    if name == "open_browser_site":
        return ja.open_website(str(args.get("site", "") or "").strip())

    if name == "google_web_search":
        return ja.google_search(str(args.get("query", "")))

    if name == "wikipedia_lookup":
        return ja.wikipedia_summary(str(args.get("topic", "")))

    if name == "current_time":
        return ja.current_time_display()

    if name == "current_date":
        return ja.current_date_display()

    if name == "youtube_play":
        return ja.play_youtube_music(str(args.get("query", "")))

    if name == "launch_local_app":
        app_alias = str(args.get("application", "")).strip().lower()
        return ja.open_application(app_alias)

    if name == "speaker_volume":
        return ja.volume_action(str(args.get("action", "")))

    if name == "check_internet":
        return ja.check_internet()

    if name == "internet_speed_check":
        return ja.measure_internet_speed()

    if name == "tell_random_joke":
        return ja.tell_joke()

    if name == "local_knowledge_query":
        q = str(args.get("question", "")).strip()
        try:
            from knowledge.rag_store import answer_from_knowledge
        except ImportError:
            return "Local knowledge unavailable; install pip install -r requirements-rag.txt."
        try:
            return answer_from_knowledge(q)
        except Exception as exc:  # noqa: BLE001
            return f"knowledge_failed: {exc}"

    if name == "ingest_document_url":
        from knowledge.url_ingest import ingest_url_into_knowledge

        return ingest_url_into_knowledge(str(args.get("url", "")).strip())

    if name == "resync_local_knowledge":
        try:
            from knowledge.rag_store import sync_knowledge_folder
        except ImportError:
            return "Knowledge indexing unavailable."
        chunks = sync_knowledge_folder()
        if chunks <= 0:
            return (
                "No new chunks this pass — files likely unchanged already. Import .txt/.md into "
                "knowledge_docs to expand."
            )
        return f"Indexed {chunks} freshly embedded chunks, Sir."

    if name == "system_open_path":
        return jst.system_open_path(str(args.get("path", "")))

    if name == "system_list_directory":
        p = str(args.get("path", ""))
        try:
            me = int(args.get("max_entries", 120))
        except (TypeError, ValueError):
            me = 120
        return jst.system_list_directory(p, max_entries=me)

    if name == "system_read_text_preview":
        p = str(args.get("path", ""))
        try:
            ml = int(args.get("max_lines", 120))
        except (TypeError, ValueError):
            ml = 120
        return jst.system_read_text_preview(p, max_lines=ml)

    if name == "system_delete_paths":
        raw_paths = args.get("paths")
        if isinstance(raw_paths, str):
            paths_list = [raw_paths]
        elif isinstance(raw_paths, list):
            paths_list = [str(x) for x in raw_paths]
        else:
            paths_list = []
        conf = bool(args.get("user_explicitly_confirmed_delete"))
        allow_dirs = bool(args.get("allow_empty_directories", False))
        return jst.system_delete_paths(
            paths_list,
            user_explicitly_confirmed_delete=conf,
            allow_empty_directories=allow_dirs,
        )

    if name == "system_launch_path_executable":
        return jst.system_launch_exe_from_path(str(args.get("program_name", "")))

    if name == "remember_persistent_note":
        note_text = str(args.get("note_text", "")).strip()
        from memory.episodic_memory import memory_append_turn

        memory_append_turn("note", note_text or "(empty)")
        return "Stored internally as a labelled note."

    if name == "desktop_notify":
        from platform_services import show_desktop_notification

        try:
            dm = int(args.get("duration_ms", 6000))
        except (TypeError, ValueError):
            dm = 6000
        return show_desktop_notification(
            str(args.get("title", "Friday")),
            str(args.get("message", "")),
            duration_ms=dm,
        )

    if name == "windows_elevated_shell":
        return ja.windows_request_elevated_shell(str(args.get("shell", "powershell")))

    if name == "exit_voice_session":
        raise JarvisExitRequest

    return f"No handler for `{name}` — ignore or ask orchestration to whitelist it."


__all__ = [
    "brain_max_tool_rounds",
    "brain_model_name",
    "brain_system_instructions",
    "invoke_tool_named",
    "is_brain_enabled",
    "run_agent_brain",
]
