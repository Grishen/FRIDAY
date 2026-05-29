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
import traceback
from typing import Any

import jarvis_actions as ja
import jarvis_system_tools as jst
from jarvis_exceptions import JarvisExitRequest


def is_brain_enabled() -> bool:
    flag = os.environ.get("JARVIS_BRAIN", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return True
    try:
        from local_llm import local_llm_mode, ollama_available

        if ollama_available() and local_llm_mode() not in ("0", "false", "no", "off"):
            return True
    except Exception:
        pass
    return False


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
            "description": (
                "Pull a Wikipedia excerpt about a topic. Adjust sentence count for depth."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "sentences": {
                        "type": "integer",
                        "description": "1-20 sentences (default 3).",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wikipedia_related_topics",
            "description": (
                "Get a short list of related Wikipedia article titles for a topic. "
                "Use when the user wants to explore around a subject or when the first "
                "lookup is ambiguous."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "limit": {"type": "integer", "description": "Default 6."},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web for information not in local knowledge. "
                "Returns a small list of {title, url, snippet}. Prefer this when the user "
                "asks about current events, prices, news, or facts unlikely to be in local docs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "1-8 results (default 5)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Schedule a reminder for the user. ``when_text`` is a natural phrase "
                "such as 'in 5 minutes', 'at 7am tomorrow', or 'at 18:30'. The reminder "
                "fires via OS notification when due."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "when_text": {"type": "string"},
                },
                "required": ["message", "when_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List the user's currently pending reminders.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": "Cancel a pending reminder by its numeric id.",
            "parameters": {
                "type": "object",
                "properties": {"reminder_id": {"type": "integer"}},
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_screen",
            "description": (
                "Capture the user's current screen and describe what is on it. Use when "
                "the user asks 'what's on my screen', 'what am I looking at', or wants "
                "help with what they are currently doing visually."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Optional focused question (e.g. 'what error is shown', "
                            "'summarize this article'). If empty, returns a general description."
                        ),
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_and_describe_photo",
            "description": (
                "Take a photo from the user's webcam and answer a question about it. "
                "Use when the user says 'take a picture', 'look at me', 'use the camera', "
                "or asks the assistant to physically see them or their surroundings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Optional question or instruction about the photo "
                            "(e.g. 'what color shirt am I wearing', 'count the people'). "
                            "If empty, returns a general description."
                        ),
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_image_file",
            "description": (
                "Describe or analyze an image file at a given local path. Use when the "
                "user references an image by file path or filename (e.g. 'look at "
                "~/Downloads/cat.jpg', 'describe the screenshot I just saved')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or ~-expanded path to the image file.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Optional question or instruction about the image.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_clipboard_image",
            "description": (
                "Read an image from the user's clipboard and describe or analyze it. "
                "Use when the user says 'what's on my clipboard', 'describe what I just "
                "copied', or otherwise indicates the image lives on the clipboard."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Optional question or instruction about the clipboard image.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_about_last_image",
            "description": (
                "Ask a follow-up question about the most recent image the assistant has "
                "looked at (screenshot, webcam photo, clipboard image, or file). Use for "
                "natural follow-ups like 'now translate the text in it' or 'what color is the car'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The follow-up question or instruction.",
                    }
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vision_analyze",
            "description": (
                "Run a structured vision analysis on a target. Use this when a single "
                "describe-style call isn't enough — e.g. extracting all text (OCR), "
                "detecting objects with bounding boxes, or producing a full structured "
                "breakdown (scene/objects/text/colors/mood/suggested next steps). The "
                "target can be a file path, an http(s) URL, or one of the keywords "
                "'screen', 'camera', 'clipboard', 'last', 'download'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Path, URL, or keyword (screen/camera/clipboard/last/download).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["describe", "ocr", "objects", "structured", "read_aloud", "code", "ui"],
                        "description": "Analysis mode. Default 'describe'.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Optional extra instruction or question.",
                    },
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_images",
            "description": (
                "Compare two or more images side-by-side and call out differences, "
                "similarities, or what changed. Pass either explicit file paths in the "
                "'paths' array, or set 'use_last_n' to compare the last N images from "
                "history (most recent first)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Image paths to compare (>=2).",
                    },
                    "use_last_n": {
                        "type": "integer",
                        "description": "If provided, ignore 'paths' and use the last N images from history.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Optional focus, e.g. 'highlight what changed in the UI'.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_pdf",
            "description": (
                "Rasterize selected pages of a PDF and analyze them with the vision model. "
                "Use when the user asks to summarize, describe, or extract info from a PDF."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "PDF file path."},
                    "prompt": {"type": "string", "description": "Optional question/instruction."},
                    "pages": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional 0-indexed pages to include (default: first 6).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "webcam_motion",
            "description": (
                "Capture a short burst of webcam frames and describe the user's motion or "
                "activity across them. Use when the user asks 'what am I doing', 'watch me', "
                "or wants action recognition rather than a still photo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number", "description": "Total capture duration (default 2)."},
                    "prompt": {"type": "string", "description": "Optional focus question."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_recent_image",
            "description": (
                "Find the most recently saved image in the user's Downloads/Desktop/"
                "Pictures/Screenshots folders. Returns the path. Use when the user "
                "references 'the picture I just downloaded' or 'the screenshot I just took'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_age_hours": {
                        "type": "number",
                        "description": "Only consider files newer than this many hours (default 24).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_context",
            "description": (
                "Snapshot of the user's current situational context as JSON: active "
                "app + window title, Focus mode, screen lock state, battery, weather, "
                "public-IP location, and Wi-Fi SSID. Use to tailor suggestions or "
                "answer 'what am I doing right now / where am I / what's my context'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_threads",
            "description": (
                "List the user's tracked topic threads (projects, people, recurring "
                "topics) along with salience and last-seen timestamps. Use to find "
                "what's still open or to pick a callback target."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "stale", "resolved"]},
                    "limit": {"type": "integer", "description": "Max items (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_thread",
            "description": (
                "Mark a topic thread as resolved (done). Pass the label or numeric id."
            ),
            "parameters": {
                "type": "object",
                "properties": {"label_or_id": {"type": "string"}},
                "required": ["label_or_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_private_mode",
            "description": (
                "Enable or disable private mode. While enabled, episodic memory "
                "and action history are NOT recorded. Disabling also purges any "
                "rows that slipped through during the private session."
            ),
            "parameters": {
                "type": "object",
                "properties": {"enable": {"type": "boolean"}},
                "required": ["enable"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_recent",
            "description": (
                "Wipe episodic memory and action_history rows from the last N minutes."
            ),
            "parameters": {
                "type": "object",
                "properties": {"minutes": {"type": "integer"}},
                "required": ["minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "await_confirmation",
            "description": (
                "Queue a confirmation gate for a high-risk action. After calling, "
                "tell the user what you're about to do and ask them to say yes or no. "
                "The voice loop will intercept the next yes/no and run or cancel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Short human-readable action label."},
                    "echo": {"type": "string", "description": "Opaque echo string (optional)."},
                },
                "required": ["label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_daily_reflection",
            "description": (
                "Synthesize a private end-of-day reflection summarizing what was "
                "discussed and done today. Use when the user asks for a recap, "
                "journal entry, or daily reflection."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_environment",
            "description": (
                "Voice-friendly one-line summary of the user's current environment "
                "(active app, focus mode, battery, location, weather). Prefer "
                "`get_active_context` when you need raw fields to reason over."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Create a new image from a text prompt and save it to disk. Use when the "
                "user explicitly asks to generate, create, draw, or render an image. "
                "Returns the saved file path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Description of the image to create."},
                    "size": {
                        "type": "string",
                        "enum": ["1024x1024", "1024x1536", "1536x1024", "auto"],
                        "description": "Image dimensions (default 1024x1024).",
                    },
                    "quality": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "auto"],
                        "description": "Render quality / cost tier (default 'high').",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_weekly_digest",
            "description": (
                "Summarize the user's past week: top topics, open loops, mood, and threads. "
                "Use when they ask for a weekly recap or 'how was my week'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_loops",
            "description": (
                "List unresolved commitments the user mentioned (e.g. 'I still need to…'). "
                "Distinct from timed reminders."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max items (default 8)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_open_loop",
            "description": "Mark an open loop as done by its numeric id.",
            "parameters": {
                "type": "object",
                "properties": {"loop_id": {"type": "integer"}},
                "required": ["loop_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_message",
            "description": (
                "Draft a short outgoing message (Slack/email tone) in the user's voice. "
                "Use when they want help wording a message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "description": "What the message should convey."},
                    "channel": {
                        "type": "string",
                        "enum": ["slack", "email", "text"],
                        "description": "Target channel style (default slack).",
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handle_running_late",
            "description": (
                "Draft (and optionally send via Slack) a lateness message. "
                "Use when the user says they're running late to a meeting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "How many minutes late (default 5)."},
                    "recipient_hint": {
                        "type": "string",
                        "description": "Optional name or channel hint for who to notify.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_vision_session",
            "description": (
                "Keep discussing the last captured image without re-capture for several minutes. "
                "Use after showing an image when the user wants extended Q&A on it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "number", "description": "Session length (default from env)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_vision_session",
            "description": "End the extended vision Q&A session on the current image.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consolidate_memory_now",
            "description": (
                "Force a memory maintenance pass: summarize backlog and prune low-salience "
                "old turns. Use sparingly — it usually runs automatically once a day."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_last_action",
            "description": (
                "Undo the most recent reversible action (reminder, knowledge note, "
                "profile capture). Optionally restrict to a specific kind."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["reminder", "note", "profile", "calendar"],
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_recent_actions",
            "description": "List the most recent tracked actions and their undo status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_user",
            "description": (
                "Switch the active speaker profile so future memory writes and reads are "
                "scoped to that user. Use when the speaker says 'I am X', 'switch user to X', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_active_user",
            "description": "Report the current active speaker profile.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daily_briefing",
            "description": (
                "Generate a spoken morning-style briefing combining weather, today's "
                "calendar, top reminders, and top news headlines."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send a plaintext email through the user's configured SMTP. Use for "
                "quick handoffs (notes to self, summaries, lists). Confirm explicitly with "
                "the user before sending to a non-default recipient."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "to": {
                        "type": "string",
                        "description": (
                            "Recipient. Leave empty to use JARVIS_EMAIL_TO_DEFAULT (the user)."
                        ),
                    },
                },
                "required": ["subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "slack_post",
            "description": (
                "Post a short message to the user's configured Slack incoming webhook "
                "(channel is fixed by webhook setup)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_now",
            "description": (
                "Run a bidirectional sync of memory/reminders/knowledge between local "
                "and the configured JARVIS_SYNC_DIR (e.g. iCloud Drive folder)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_list_today",
            "description": (
                "List today's calendar events from the user's local Calendar.app (macOS only)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_list_upcoming",
            "description": (
                "List upcoming calendar events within the next N hours "
                "(macOS Calendar.app only)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "1-72 (default 24)."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create_event",
            "description": (
                "Create a calendar event in macOS Calendar.app. Provide a clear title, "
                "ISO-ish start time (or relative phrase), and optional duration."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "when_text": {
                        "type": "string",
                        "description": (
                            "Natural phrase such as 'tomorrow at 3pm', 'today at 18:30', "
                            "or 'Friday at 9am for 45 minutes'."
                        ),
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Defaults to 30 if not specified.",
                    },
                    "notes": {"type": "string"},
                },
                "required": ["title", "when_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unified_ask",
            "description": (
                "Answer a complex question by combining the user's memory, local "
                "knowledge base, live web search, and Wikipedia into one grounded answer. "
                "Use for broad or open-ended questions where a single source is insufficient."
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
            "name": "web_ingest_top_result",
            "description": (
                "Run a web_search and download the top result into the local knowledge base "
                "so future answers can cite it. Use when the user wants to permanently "
                "remember a web source about a topic."
            ),
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
            "name": "spotify_play",
            "description": "Search Spotify and start playback (requires Spotify credentials in env).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Track or artist search."},
                    "uri": {"type": "string", "description": "Optional Spotify URI."},
                    "device_name": {"type": "string", "description": "Optional output device name."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_pause",
            "description": "Pause Spotify playback.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_now_playing",
            "description": "Report current Spotify track and device.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_transfer",
            "description": "Move Spotify playback to a named device/speaker.",
            "parameters": {
                "type": "object",
                "properties": {"device_name": {"type": "string"}},
                "required": ["device_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "homekit_set_scene",
            "description": (
                "Run a HomeKit scene via macOS Shortcuts (e.g. Good Night, Movie Mode)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "homekit_set_light",
            "description": "Turn a HomeKit light on/off or dim via Shortcuts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "on": {"type": "boolean"},
                    "brightness": {"type": "integer", "description": "1-100 if dimming."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_routines",
            "description": "List the user's configured automations (scheduled or focus-triggered).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_routine",
            "description": "Manually run a routine by id or name.",
            "parameters": {
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_routine",
            "description": (
                "Create an automation from natural language, e.g. "
                "'every weekday at 8 am daily briefing and open loops'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"definition": {"type": "string"}},
                "required": ["definition"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "launch_local_app",
            "description": (
                "Open a local application by name (Safari, Notes, Terminal, VS Code, etc.). "
                "On macOS any installed app name works via open -a."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "application": {
                        "type": "string",
                        "description": (
                            "App name or alias: safari, chrome, notes, terminal, vscode, "
                            "calculator, notepad, or any macOS app name."
                        ),
                    },
                },
                "required": ["application"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Get current weather for a city. Uses OPENWEATHER_API_KEY. "
                "If city omitted, uses JARVIS_DEFAULT_CITY from env."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. San Francisco",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": (
                "Open a URL in a headless browser, optionally wait for a selector, "
                "and return page text or a screenshot path. Requires Playwright."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "selector": {"type": "string", "description": "CSS selector to extract."},
                    "wait_for": {"type": "string", "description": "CSS selector to wait for."},
                    "screenshot": {"type": "boolean", "description": "Save a screenshot."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Open a URL and click a CSS selector (Playwright).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "selector": {"type": "string"},
                    "wait_for": {"type": "string"},
                },
                "required": ["url", "selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "Open a URL, fill a form field, optionally submit (Playwright).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "submit": {"type": "boolean"},
                },
                "required": ["url", "selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "macos_music",
            "description": "Control Apple Music on macOS (play, pause, next, now playing).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "next", "previous", "now_playing"],
                    },
                    "query": {"type": "string", "description": "Search query when action=play."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "macos_volume",
            "description": "Set or adjust macOS system volume (0-100) or mute.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["set", "up", "down", "mute"]},
                    "level": {"type": "integer", "description": "0-100 when action=set."},
                    "step": {"type": "integer", "description": "Step for up/down (default 10)."},
                    "mute": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "macos_send_imessage",
            "description": "Send an iMessage on macOS to a contact name or phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["recipient", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "macos_create_note",
            "description": "Create a note in Apple Notes on macOS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python_sandbox",
            "description": (
                "Run short Python code in a restricted sandbox. Requires JARVIS_CODE_SANDBOX=1. "
                "Use for quick calculations or data transforms — not for destructive OS actions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "timeout_s": {"type": "number"},
                    "network": {"type": "boolean"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell_sandbox",
            "description": (
                "Run a shell command in a restricted sandbox. Requires JARVIS_CODE_SANDBOX=1."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_s": {"type": "number"},
                },
                "required": ["command"],
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
            "name": "save_knowledge_note",
            "description": (
                "Save a durable fact into local knowledge_docs so future RAG lookups can find it."
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
If file tools are enabled: only operate on paths inside the configured sandbox (docs/FILE_TOOLS.md); before deleting, ensure the user explicitly named those paths.
When answering from memory or local knowledge, sound natural and conversational — not like a database readout.
If a "Proactive recall" block appears, briefly weave the recalled detail into the reply ("Right, you mentioned X last time — …") instead of ignoring it. Keep it light, not interrogative."""

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
- When the user asks about their own docs, notes, or saved facts, prefer `local_knowledge_query` before guessing.
- For durable facts the user wants indexed long-term, use `save_knowledge_note` (not just episodic memory).
- Vision tools — pick the most specific one for the intent; never invent an image you can't see:
    * `describe_screen` — current desktop, general narration.
    * `capture_and_describe_photo` — use the webcam; Boss said "look at me" / "take a picture".
    * `describe_image_file` — Boss referenced a file path.
    * `describe_clipboard_image` — Boss copied an image.
    * `ask_about_last_image` — natural follow-ups about the most recent image.
    * `vision_analyze` — when a deeper analysis is required (mode = ocr / objects / structured / code / ui), or when the target is a URL or 'download' (recent file). Prefer ocr for text-heavy images, ui for screenshot triage, code for source-code captures.
    * `compare_images` — Boss wants a diff/comparison; pass `use_last_n: 2` for "compare the last two".
    * `analyze_pdf` — Boss references a PDF.
    * `webcam_motion` — "watch me", "what am I doing", continuous action over a few seconds.
    * `find_recent_image` — Boss references "the picture I just downloaded" / "the recent screenshot"; chain the returned path into `describe_image_file` or `vision_analyze`.
    * `generate_image` — Boss explicitly asks to *create / generate / draw / render* a new image. Never call this when Boss only wants to *see* something that already exists.
- If a "Proactive recall" hint appears in the system context, weave a brief, natural acknowledgment of the recalled detail into your reply ("Right, you mentioned X last time — …") rather than ignoring it. Keep it short; do not over-explain that you remembered.
- Never imply covert Windows Administrator privileges: genuine elevation requires Boss-approved UAC; unrestricted silent admin automation is deliberately unsupported (docs/WINDOWS_ADMIN.md).
- File open/list/preview/delete helpers (when enabled) are confined to configured roots; widen roots only when Boss requests; never guess sensitive system paths for deletion."""


def brain_system_instructions() -> str:
    """Resolve system prompt: explicit env override → personas module → legacy preset."""
    override = os.environ.get("JARVIS_BRAIN_SYSTEM_PROMPT", "").strip()
    if override:
        return override
    # Try the new personas module (supports user-switchable personas + verbosity + address).
    try:
        from personas import compose_system_prompt, get_persona_key

        if get_persona_key() in {"jarvis", "friday"}:
            # Keep the rich legacy preset as the *base* so persona/verbosity overlays it.
            legacy = SYSTEM_FRIDAY if get_persona_key() == "friday" else SYSTEM_JARVIS
            return compose_system_prompt(base=legacy)
        return compose_system_prompt()
    except Exception:
        pass
    key = os.environ.get("JARVIS_BRAIN_PERSONA", "jarvis").strip().lower()
    if key in ("friday", "ops", "chief"):
        return SYSTEM_FRIDAY
    return SYSTEM_JARVIS


def _cloud_quota_or_rate_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    if "ratelimit" in name or "quota" in name:
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "429",
            "402",
            "insufficient_quota",
            "rate limit",
            "quota",
            "billing",
            "exceeded your current quota",
        )
    )


def _try_local_agent_brain(*, user_utterance: str, episodic_prefill: str) -> Optional[str]:
    try:
        from local_llm import ollama_available, run_local_agent_brain, run_local_brain

        if not ollama_available():
            return None
        try:
            return run_local_agent_brain(
                user_utterance=user_utterance,
                episodic_prefill=episodic_prefill,
            )
        except Exception:
            traceback.print_exc()
            return run_local_brain(
                user_utterance=user_utterance,
                episodic_prefill=episodic_prefill,
            )
    except Exception:
        traceback.print_exc()
        return None


def run_agent_brain(*, user_utterance: str, episodic_prefill: str) -> str:
    """Chat Completions with tools loop; narration fit for ElevenLabs / local speak()."""
    cloud_key = os.environ.get("OPENAI_API_KEY", "").strip()
    private = False
    try:
        from privacy import is_private

        private = is_private()
    except Exception:
        pass

    try:
        from local_llm import should_prefer_local_first, should_use_local

        if should_prefer_local_first(private=private) or should_use_local(
            private=private, cloud_key_missing=not cloud_key
        ):
            local_reply = _try_local_agent_brain(
                user_utterance=user_utterance,
                episodic_prefill=episodic_prefill,
            )
            if local_reply:
                return local_reply
    except Exception:
        pass

    if not cloud_key:
        local_reply = _try_local_agent_brain(
            user_utterance=user_utterance,
            episodic_prefill=episodic_prefill,
        )
        if local_reply:
            return local_reply
        raise RuntimeError(
            "No brain available: set OPENAI_API_KEY or start Ollama with JARVIS_LOCAL_LLM=prefer."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "Install the OpenAI client: pip install -r requirements-brain.txt"
        ) from exc

    client = OpenAI(api_key=cloud_key)

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

    try:
        for _ in range(brain_max_tool_rounds()):
            try:
                completion = client.chat.completions.create(
                    model=brain_model_name(),
                    messages=messages,
                    tools=TOOL_SPECS,
                    tool_choice="auto",
                    temperature=0.38,
                )
            except Exception as exc:
                if _cloud_quota_or_rate_error(exc):
                    local_reply = _try_local_agent_brain(
                        user_utterance=user_utterance,
                        episodic_prefill=episodic_prefill,
                    )
                    if local_reply:
                        return local_reply
                raise

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
    except Exception as exc:
        if _cloud_quota_or_rate_error(exc):
            local_reply = _try_local_agent_brain(
                user_utterance=user_utterance,
                episodic_prefill=episodic_prefill,
            )
            if local_reply:
                return local_reply
        raise


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
        try:
            sentences = int(args.get("sentences", 3))
        except (TypeError, ValueError):
            sentences = 3
        return ja.wikipedia_summary(str(args.get("topic", "")), sentences=sentences)

    if name == "wikipedia_related_topics":
        try:
            limit = int(args.get("limit", 6))
        except (TypeError, ValueError):
            limit = 6
        related = ja.wikipedia_related(str(args.get("topic", "")), limit=limit)
        if not related:
            return "No related Wikipedia topics found."
        return "Related topics: " + ", ".join(related)

    if name == "web_search":
        from web_search import format_results_as_json, search_web

        try:
            limit = int(args.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        results = search_web(str(args.get("query", "")), limit=limit)
        if not results:
            return "No web results found, or network/search backend unavailable."
        return format_results_as_json(results)

    if name == "set_reminder":
        from reminders import add_reminder, describe_reminder_due, parse_reminder

        message = str(args.get("message", "")).strip()
        when_text = str(args.get("when_text", "")).strip()
        if not message or not when_text:
            return "Need both message and when_text."
        _msg, due, recurrence = parse_reminder(f"remind me to {message} {when_text}")
        if due is None:
            return f"Could not parse a time from '{when_text}'."
        rid = add_reminder(message, due.timestamp(), recurrence=recurrence)
        tag = f" (recurring {recurrence})" if recurrence else ""
        return f"Reminder #{rid} set for {describe_reminder_due(due)}{tag}: {message}"

    if name == "list_reminders":
        from datetime import datetime

        from reminders import describe_reminder_due, list_pending_reminders

        items = list_pending_reminders(limit=20)
        if not items:
            return "No pending reminders."
        lines = []
        for rid, msg, due_at, recurrence in items:
            tag = f" (recurring {recurrence})" if recurrence else ""
            lines.append(
                f"#{rid} at {describe_reminder_due(datetime.fromtimestamp(due_at))}{tag}: {msg}"
            )
        return "Pending reminders: " + " | ".join(lines)

    if name == "cancel_reminder":
        from reminders import cancel_reminder as _cancel

        try:
            rid = int(args.get("reminder_id", 0))
        except (TypeError, ValueError):
            rid = 0
        if rid <= 0:
            return "Provide a positive reminder_id."
        ok = _cancel(rid)
        return f"Cancelled reminder #{rid}." if ok else f"No pending reminder #{rid} to cancel."

    if name == "describe_screen":
        from vision import describe_screen

        return describe_screen(prompt=str(args.get("prompt", "")))

    if name == "capture_and_describe_photo":
        from vision import describe_webcam

        return describe_webcam(prompt=str(args.get("prompt", "")))

    if name == "describe_image_file":
        from vision import describe_image

        path = str(args.get("path", "")).strip()
        if not path:
            return "Provide an image file path."
        return describe_image(path, prompt=str(args.get("prompt", "")))

    if name == "describe_clipboard_image":
        from vision import describe_clipboard_image

        return describe_clipboard_image(prompt=str(args.get("prompt", "")))

    if name == "ask_about_last_image":
        from vision import ask_about_last_image

        prompt = str(args.get("prompt", "")).strip()
        if not prompt:
            return "Provide a follow-up question or instruction."
        try:
            from vision_session import is_active, session_ask

            if is_active():
                return session_ask(prompt)
        except Exception:
            pass
        return ask_about_last_image(prompt)

    if name == "vision_analyze":
        from vision import analyze_image, analyze_target

        target = str(args.get("target", "")).strip()
        mode = str(args.get("mode", "describe")).strip() or "describe"
        prompt = str(args.get("prompt", "")).strip()
        if not target:
            return "Provide a target (path, URL, or screen/camera/clipboard/last/download)."

        low = target.lower()
        # Keyword targets: use analyze_target's routing then route through analyze_image for non-describe modes.
        if low in ("screen", "camera", "webcam", "clipboard", "last", "latest", "download", "downloads", "recent") \
                or target.startswith(("http://", "https://", "pdf:")):
            if mode == "describe":
                return analyze_target(target, prompt=prompt, mode=mode)
            # Capture once via analyze_target's helpers, then run a specific mode.
            from vision import (
                analyze_image as _ai, capture_clipboard_image, capture_webcam,
                take_screenshot, fetch_url_to_temp, find_recent_image, get_last_image,
            )
            if low in ("screen", "desktop"):
                ok, info = take_screenshot()
            elif low in ("camera", "webcam"):
                ok, info = capture_webcam()
            elif low in ("clipboard", "paste"):
                ok, info = capture_clipboard_image()
            elif low in ("last", "latest", "previous"):
                p, _ = get_last_image()
                ok, info = (bool(p), p or "No recent image.")
            elif low in ("download", "downloads", "recent"):
                p = find_recent_image()
                ok, info = (bool(p), p or "No recent image found.")
            elif target.startswith(("http://", "https://")):
                ok, info = fetch_url_to_temp(target)
            else:
                ok, info = False, "Unsupported target."
            if not ok:
                return info
            return _ai(info, prompt=prompt, mode=mode)["text"] or "No result."

        # Plain file path
        res = analyze_image(target, prompt=prompt, mode=mode)
        return res.get("text") or res.get("error") or "No result."

    if name == "compare_images":
        from vision import analyze_images, image_history

        paths = args.get("paths") or []
        n = args.get("use_last_n")
        if (not paths) and isinstance(n, int) and n >= 2:
            hist = image_history()
            if len(hist) < n:
                return f"Only {len(hist)} image(s) in history."
            paths = [h["path"] for h in hist[-n:]]
        if not isinstance(paths, list) or len(paths) < 2:
            return "Provide at least two image paths (or set use_last_n >= 2)."
        prompt = str(args.get("prompt", "")).strip()
        res = analyze_images([str(p) for p in paths], prompt=prompt, mode="compare")
        return res.get("text") or res.get("error") or "No result."

    if name == "analyze_pdf":
        from vision import analyze_pdf

        path = str(args.get("path", "")).strip()
        if not path:
            return "Provide a PDF path."
        prompt = str(args.get("prompt", "")).strip()
        pages_arg = args.get("pages")
        pages = None
        if isinstance(pages_arg, list):
            try:
                pages = [int(x) for x in pages_arg]
            except (TypeError, ValueError):
                pages = None
        return analyze_pdf(path, prompt=prompt, pages=pages)

    if name == "webcam_motion":
        from vision import describe_webcam_motion

        try:
            seconds = float(args.get("seconds", 2.0))
        except (TypeError, ValueError):
            seconds = 2.0
        seconds = max(1.0, min(8.0, seconds))
        frames = max(2, min(8, int(round(seconds / 0.6))))
        return describe_webcam_motion(str(args.get("prompt", "")), frames=frames, interval_s=0.6)

    if name == "find_recent_image":
        from vision import find_recent_image

        try:
            max_h = float(args.get("max_age_hours", 24.0))
        except (TypeError, ValueError):
            max_h = 24.0
        path = find_recent_image(max_age_hours=max_h)
        return path or "No recent image found in Downloads/Desktop/Pictures/Screenshots."

    if name == "generate_image":
        from vision import generate_image

        prompt = str(args.get("prompt", "")).strip()
        if not prompt:
            return "Provide a prompt describing the image to generate."
        size = str(args.get("size", "1024x1024")).strip() or "1024x1024"
        quality = str(args.get("quality", "high")).strip() or "high"
        result = generate_image(prompt, size=size, quality=quality)
        if result.get("ok"):
            return f"Image saved to {result.get('path')}."
        return result.get("error") or "Image generation failed."

    if name == "build_weekly_digest":
        from weekly_digest import build_weekly_digest

        return build_weekly_digest() or "Not enough conversation history for a weekly digest yet."

    if name == "list_open_loops":
        from open_loops import describe_for_voice

        try:
            limit = int(args.get("limit", 8))
        except (TypeError, ValueError):
            limit = 8
        return describe_for_voice(limit=limit)

    if name == "resolve_open_loop":
        from open_loops import resolve_loop

        try:
            loop_id = int(args.get("loop_id", 0))
        except (TypeError, ValueError):
            loop_id = 0
        if loop_id <= 0:
            return "Provide a positive loop_id."
        ok = resolve_loop(loop_id)
        return f"Marked open loop #{loop_id} done." if ok else f"No open loop #{loop_id} found."

    if name == "draft_message":
        from message_draft import draft_message

        intent = str(args.get("intent", "")).strip()
        if not intent:
            return "Provide intent describing what the message should say."
        channel = str(args.get("channel", "slack")).strip() or "slack"
        return draft_message(intent, channel=channel)

    if name == "handle_running_late":
        from message_draft import handle_running_late

        try:
            minutes = int(args.get("minutes", 5))
        except (TypeError, ValueError):
            minutes = 5
        recipient = str(args.get("recipient_hint", "")).strip()
        return handle_running_late(minutes, recipient_hint=recipient)

    if name == "start_vision_session":
        from vision_session import start_vision_session

        mins = args.get("minutes")
        try:
            minutes = float(mins) if mins is not None else None
        except (TypeError, ValueError):
            minutes = None
        return start_vision_session(minutes=minutes)

    if name == "end_vision_session":
        from vision_session import end_vision_session

        return end_vision_session()

    if name == "list_routines":
        from routines import describe_routines_for_voice

        return describe_routines_for_voice()

    if name == "run_routine":
        from routines import run_routine_by_id_or_name

        target = str(args.get("target", "")).strip()
        if not target:
            return "Provide routine id or name."
        # Brain path: return text only (no TTS from here).
        from routines import get_routine, find_routine_by_name, run_routine

        routine = get_routine(int(target)) if target.isdigit() else find_routine_by_name(target)
        if not routine:
            return f"No routine matching '{target}'."

        results: list[str] = []
        for action in routine.actions:
            try:
                from routines import execute_action

                results.append(
                    execute_action(action, speak_fn=lambda _m: None)
                )
            except Exception as exc:
                results.append(str(exc))
        return f"Ran routine '{routine.name}': " + " | ".join(results)

    if name == "create_routine":
        from routines import parse_and_create_routine

        return parse_and_create_routine(str(args.get("definition", "")))

    if name == "get_active_context":
        import awareness as aw

        app = aw.active_app() or {}
        return json.dumps({
            "active_app": app.get("name"),
            "window_title": app.get("window_title"),
            "focus_mode": aw.focus_mode(),
            "screen_locked": aw.screen_locked(),
            "battery_percent": aw.battery_percent(),
            "on_battery": aw.is_on_battery(),
            "weather": aw.weather_summary(),
            "location": aw.public_ip_geo(),
            "wifi_ssid": aw.network_ssid(),
        }, default=str)

    if name == "describe_environment":
        import awareness as aw

        return aw.describe_environment()

    if name == "list_threads":
        from topic_threads import list_threads

        status = str(args.get("status", "open")).strip() or "open"
        limit = int(args.get("limit", 10) or 10)
        threads = list_threads(status=status, limit=limit)
        if not threads:
            return f"No {status} threads."
        return json.dumps([
            {"id": t.id, "label": t.label, "kind": t.kind,
             "salience": t.salience, "last_seen": t.last_seen,
             "notes_tail": t.notes[-3:] if t.notes else []}
            for t in threads
        ])

    if name == "resolve_thread":
        from topic_threads import resolve_thread

        label = args.get("label_or_id")
        if isinstance(label, str):
            try:
                label = int(label)
            except ValueError:
                pass
        if not label:
            return "Provide label_or_id."
        t = resolve_thread(label)
        return f"Resolved {t.label}." if t else "No matching thread."

    if name == "build_daily_reflection":
        from reflection import build_daily_reflection

        return build_daily_reflection()

    if name == "set_private_mode":
        from privacy import set_private, disable_private_and_purge

        enable = bool(args.get("enable", True))
        if enable:
            set_private(True)
            return "Private mode enabled. Nothing will be logged."
        result = disable_private_and_purge()
        n = result.get("episodic_deleted", 0) + result.get("actions_deleted", 0)
        return f"Private mode disabled; purged {n} record(s)."

    if name == "forget_recent":
        from privacy import forget_recent_minutes

        try:
            minutes = int(args.get("minutes", 5))
        except (TypeError, ValueError):
            minutes = 5
        result = forget_recent_minutes(minutes)
        return json.dumps(result)

    if name == "await_confirmation":
        from privacy import await_confirmation

        label = str(args.get("label", "high-risk action"))
        echo = str(args.get("echo", ""))
        await_confirmation(label, perform=lambda: f"Confirmed via voice ({echo})")
        return f"Queued confirmation for: {label}. Awaiting yes/no."

    if name == "run_python_sandbox":
        from code_sandbox import run_python

        code = str(args.get("code", ""))
        timeout = float(args.get("timeout_s", 10.0))
        network = bool(args.get("network", False))
        result = run_python(code, timeout_s=timeout, network=network)
        return json.dumps({k: v for k, v in result.items() if k != "value"} |
                          ({"value": result.get("value")} if result.get("value") is not None else {}),
                          default=str)

    if name == "run_shell_sandbox":
        from code_sandbox import run_shell

        cmd = str(args.get("command", ""))
        timeout = float(args.get("timeout_s", 10.0))
        return json.dumps(run_shell(cmd, timeout_s=timeout), default=str)

    if name == "browser_open":
        import browser_tool as bt

        url = str(args.get("url", ""))
        selector = str(args.get("selector", ""))
        wait_for = str(args.get("wait_for", ""))
        screenshot = bool(args.get("screenshot", False))
        return json.dumps(bt.open_and_extract(url, wait_for=wait_for, selector=selector,
                                              screenshot=screenshot), default=str)

    if name == "browser_click":
        import browser_tool as bt

        return json.dumps(bt.click(str(args.get("url", "")), str(args.get("selector", "")),
                                   wait_for=str(args.get("wait_for", ""))), default=str)

    if name == "browser_fill":
        import browser_tool as bt

        return json.dumps(bt.fill(str(args.get("url", "")), str(args.get("selector", "")),
                                  str(args.get("text", "")),
                                  submit=bool(args.get("submit", False))), default=str)

    if name == "macos_music":
        import mac_automation as m

        action = str(args.get("action", "play")).lower()
        if action == "play":
            q = str(args.get("query", ""))
            return json.dumps(m.music_search_and_play(q) if q else m.music_play(), default=str)
        if action == "pause":
            return json.dumps(m.music_pause(), default=str)
        if action == "next":
            return json.dumps(m.music_next(), default=str)
        if action == "previous":
            return json.dumps(m.music_previous(), default=str)
        if action == "now_playing":
            return json.dumps(m.music_now_playing(), default=str)
        return json.dumps({"ok": False, "message": f"unknown action '{action}'"})

    if name == "macos_volume":
        import mac_automation as m

        try:
            level = int(args.get("level", -1))
        except (TypeError, ValueError):
            level = -1
        action = str(args.get("action", "set")).lower()
        if action == "up":
            return json.dumps(m.system_volume_up(int(args.get("step", 10))), default=str)
        if action == "down":
            return json.dumps(m.system_volume_down(int(args.get("step", 10))), default=str)
        if action == "mute":
            return json.dumps(m.mute_system(bool(args.get("mute", True))), default=str)
        if level >= 0:
            return json.dumps(m.set_system_volume(level), default=str)
        return json.dumps({"ok": False, "message": "provide level 0-100 or action up/down/mute"})

    if name == "macos_send_imessage":
        import mac_automation as m

        return json.dumps(m.send_imessage(str(args.get("recipient", "")),
                                          str(args.get("text", ""))), default=str)

    if name == "macos_create_note":
        import mac_automation as m

        return json.dumps(m.create_note(str(args.get("title", "Untitled")),
                                        str(args.get("body", ""))), default=str)

    if name == "spotify_play":
        import smart_home as sh

        return json.dumps(sh.spotify_play(query=str(args.get("query", "")),
                                          uri=str(args.get("uri", "")),
                                          device_name=str(args.get("device_name", ""))), default=str)

    if name == "spotify_pause":
        import smart_home as sh

        return json.dumps(sh.spotify_pause(), default=str)

    if name == "spotify_now_playing":
        import smart_home as sh

        return json.dumps(sh.spotify_now_playing(), default=str)

    if name == "spotify_transfer":
        import smart_home as sh

        device = str(args.get("device_name", "")).strip()
        if not device:
            return "device_name required."
        return json.dumps(sh.spotify_transfer(device), default=str)

    if name == "homekit_set_scene":
        import smart_home as sh

        return json.dumps(sh.homekit_set_scene(str(args.get("name", ""))), default=str)

    if name == "homekit_set_light":
        import smart_home as sh

        light = str(args.get("name", "")).strip()
        if not light:
            return "name required."
        on = bool(args.get("on", True))
        brightness = args.get("brightness")
        b = int(brightness) if brightness is not None else None
        return json.dumps(sh.homekit_set_light(light, on=on, brightness=b), default=str)

    if name == "consolidate_memory_now":
        from memory.episodic_memory import memory_consolidate

        result = memory_consolidate(force=True)
        return f"Memory maintenance done: summarized={result.get('summarized')}, pruned={result.get('pruned')}."

    if name == "undo_last_action":
        from action_history import undo_last

        kind = (args.get("kind") or "").strip().lower() or None
        return undo_last(kind=kind)

    if name == "describe_recent_actions":
        from action_history import describe_recent_actions

        return describe_recent_actions()

    if name == "switch_user":
        from user_profiles import set_active_user

        uid = str(args.get("user_id", "")).strip()
        if not uid:
            return "user_id required."
        new_uid = set_active_user(uid, display_name=uid)
        return f"Active speaker switched to {new_uid}."

    if name == "describe_active_user":
        from user_profiles import describe_active_user

        return describe_active_user()

    if name == "daily_briefing":
        from briefing import build_daily_briefing

        return build_daily_briefing()

    if name == "send_email":
        from outgoing import send_email

        return send_email(
            subject=str(args.get("subject", "")),
            body=str(args.get("body", "")),
            to=str(args.get("to", "")) or None,
        )

    if name == "slack_post":
        from outgoing import slack_post

        return slack_post(str(args.get("text", "")))

    if name == "sync_now":
        from sync_service import sync_now

        return sync_now()

    if name == "calendar_list_today":
        from calendar_service import calendar_available, calendar_today_events

        if not calendar_available():
            from calendar_service import calendar_unavailable_message

            return calendar_unavailable_message()
        items = calendar_today_events(limit=10)
        if not items:
            return "No calendar events today."
        lines = [f"{it['title']} ({it['start']} – {it['end']}) [{it['calendar']}]" for it in items]
        return "Today: " + " | ".join(lines)

    if name == "calendar_list_upcoming":
        from calendar_service import calendar_available, calendar_upcoming_events

        if not calendar_available():
            from calendar_service import calendar_unavailable_message

            return calendar_unavailable_message()
        try:
            hours = int(args.get("hours", 24))
        except (TypeError, ValueError):
            hours = 24
        items = calendar_upcoming_events(hours=hours, limit=10)
        if not items:
            return f"No calendar events in the next {hours} hours."
        lines = [f"{it['title']} ({it['start']} – {it['end']}) [{it['calendar']}]" for it in items]
        return f"Next {hours}h: " + " | ".join(lines)

    if name == "calendar_create_event":
        from calendar_service import (
            calendar_available,
            calendar_create_event,
            parse_calendar_phrase,
        )

        if not calendar_available():
            from calendar_service import calendar_unavailable_message

            return calendar_unavailable_message()

        title = str(args.get("title", "")).strip()
        when_text = str(args.get("when_text", "")).strip()
        notes = str(args.get("notes", "")).strip()
        try:
            duration = int(args.get("duration_minutes", 30))
        except (TypeError, ValueError):
            duration = 30
        if not title or not when_text:
            return "Need both title and when_text."
        parsed_title, start_dt, parsed_dur = parse_calendar_phrase(f"{title} {when_text}")
        if start_dt is None:
            return f"Could not parse a start time from '{when_text}'."
        # Honor explicit duration from caller when provided.
        if duration and duration != 30:
            parsed_dur = duration
        chosen_title = title or parsed_title or "Event"
        return calendar_create_event(
            title=chosen_title,
            start=start_dt,
            duration_minutes=parsed_dur,
            notes=notes,
        )

    if name == "unified_ask":
        from unified_ask import unified_ask as _uask

        result = _uask(str(args.get("question", "")))
        reply = result.get("reply") or ""
        sources = result.get("sources") or []
        if sources:
            return reply + "\n\nSources: " + ", ".join(sources[:5])
        return reply

    if name == "web_ingest_top_result":
        from knowledge.rag_store import sync_knowledge_folder
        from knowledge.url_ingest import ingest_url_into_knowledge
        from web_search import search_web

        results = search_web(str(args.get("query", "")), limit=3)
        if not results:
            return "No web results to ingest."
        top_url = results[0].get("url", "")
        if not top_url:
            return "Top web result had no usable URL."
        msg = ingest_url_into_knowledge(top_url)
        try:
            indexed = sync_knowledge_folder()
            if indexed:
                msg += f" Indexed {indexed} new chunks."
        except Exception:
            pass
        return f"Top result: {top_url}. {msg}"

    if name == "current_time":
        return ja.current_time_display()

    if name == "current_date":
        return ja.current_date_display()

    if name == "launch_local_app":
        app_alias = str(args.get("application", "")).strip()
        if not app_alias:
            return "Provide an application name."
        try:
            return ja.open_application_by_name(app_alias)
        except AttributeError:
            return ja.open_application(app_alias.lower())

    if name == "get_weather":
        from briefing import fetch_weather_for_city

        city = str(args.get("city", "") or "").strip()
        if not city:
            city = os.environ.get("JARVIS_DEFAULT_CITY", "").strip()
        if not city:
            return "Provide a city or set JARVIS_DEFAULT_CITY in .env."
        summary = fetch_weather_for_city(city)
        return summary or f"Could not fetch weather for {city}. Check OPENWEATHER_API_KEY."

    if name == "youtube_play":
        return ja.play_youtube_music(str(args.get("query", "")))

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

    if name == "save_knowledge_note":
        note_text = str(args.get("note_text", "")).strip()
        from knowledge.note_writer import save_voice_note
        from knowledge.rag_store import sync_knowledge_folder

        msg = save_voice_note(note_text)
        try:
            sync_knowledge_folder()
        except Exception:
            pass
        return msg

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
