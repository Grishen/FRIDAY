"""Draft outgoing messages in the user's voice + lateness handoffs."""

from __future__ import annotations

import os
import re
from typing import Optional


def _sample_user_voice(*, max_lines: int = 15) -> str:
    try:
        from memory.episodic_memory import memory_recent_rows
    except Exception:
        return ""
    lines: list[str] = []
    for role, text in memory_recent_rows(limit=120):
        if role == "user":
            clean = (text or "").strip()
            if clean and len(clean) > 12:
                lines.append(clean)
    return "\n".join(lines[-max_lines:])


def draft_message(intent: str, *, channel: str = "slack") -> str:
    """Draft a short message matching the user's typical tone."""
    intent = (intent or "").strip()
    if not intent:
        return "What should the message say?"

    samples = _sample_user_voice()
    if os.environ.get("OPENAI_API_KEY", "").strip():
        try:
            from openai import OpenAI

            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
            ch = (channel or "slack").strip().lower()
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Draft a concise {ch} message for the user. Match their voice "
                            "from the samples. Output ONLY the message body, no quotes."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Intent: {intent}\n\nUser voice samples:\n{samples or '(none)'}",
                    },
                ],
                temperature=0.45,
            )
            body = getattr(completion.choices[0].message, "content", None) or ""
            body = body.strip()
            if body:
                return body
        except Exception:
            pass

    return f"Running late — {intent}" if "late" in intent.lower() else intent


def handle_running_late(minutes: int = 5, *, recipient_hint: str = "") -> str:
    """Draft + optionally send lateness messages via Slack/email."""
    mins = max(1, int(minutes or 5))
    hint = (recipient_hint or "").strip()
    body = draft_message(
        f"I'll be about {mins} minutes late" + (f" to meet {hint}" if hint else ""),
        channel="slack",
    )

    sent_parts: list[str] = [f"Draft: {body}"]

    try:
        from outgoing import slack_configured, slack_post

        if slack_configured() and os.environ.get("JARVIS_AUTO_LATE_SLACK", "0").lower() in (
            "1", "true", "yes",
        ):
            result = slack_post(body)
            sent_parts.append(result)
    except Exception:
        pass

    try:
        from calendar_service import calendar_available, calendar_upcoming_events

        if calendar_available():
            events = calendar_upcoming_events(hours=2, limit=1) or []
            if events:
                title = events[0].get("title", "your meeting")
                sent_parts.append(f"Your next event is {title}.")
    except Exception:
        pass

    return " ".join(sent_parts)


_LATE_RE = re.compile(
    r"(?:running|i'?m|i am)\s+(?:(\d+)\s*(?:min|minute|minutes|m)\s+)?late|"
    r"(\d+)\s*(?:min|minute|minutes|m)\s+late",
    re.I,
)


def parse_running_late(text: str) -> Optional[tuple[int, str]]:
    m = _LATE_RE.search(text or "")
    if not m:
        return None
    mins = 5
    if m.group(1):
        mins = int(m.group(1))
    elif m.group(2):
        mins = int(m.group(2))
    recipient = ""
    for person in re.findall(r"\bto\s+([A-Z][a-z]+)\b", text or ""):
        recipient = person
        break
    return mins, recipient


__all__ = ["draft_message", "handle_running_late", "parse_running_late"]
