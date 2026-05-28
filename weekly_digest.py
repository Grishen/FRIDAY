"""Weekly digest — summarize the past week of conversations and open threads."""

from __future__ import annotations

import os
from typing import Optional


def _collect_user_lines() -> list[str]:
    try:
        from memory.episodic_memory import memory_recent_rows
    except Exception:
        return []
    lines: list[str] = []
    try:
        rows = memory_recent_rows(limit=400)
    except Exception:
        return []
    for role, text in rows:
        if role == "user":
            clean = (text or "").strip()
            if clean:
                lines.append(clean)
    return lines[-80:]


def _top_topics(user_lines: list[str]) -> list[str]:
    from collections import Counter
    import re

    words: Counter = Counter()
    stop = {
        "the", "a", "an", "and", "or", "to", "in", "on", "for", "i", "you", "my",
        "me", "we", "it", "is", "was", "that", "this", "with", "at", "be", "have",
        "do", "just", "like", "sir", "boss",
    }
    for line in user_lines:
        for w in re.findall(r"[a-zA-Z']{4,}", line.lower()):
            if w not in stop:
                words[w] += 1
    return [w for w, _ in words.most_common(5)]


def build_weekly_digest() -> str:
    user_lines = _collect_user_lines()
    topics = _top_topics(user_lines)

    loop_bits: list[str] = []
    try:
        from open_loops import list_open_loops

        loop_bits = [l.text for l in list_open_loops(limit=5)]
    except Exception:
        pass

    thread_bits: list[str] = []
    try:
        from topic_threads import list_threads

        thread_bits = [t.label for t in list_threads(status="open", limit=5)]
    except Exception:
        pass

    mood_line = ""
    try:
        from mood_trajectory import mood_trajectory_summary

        mood_line = mood_trajectory_summary()
    except Exception:
        pass

    if os.environ.get("OPENAI_API_KEY", "").strip():
        llm = _llm_digest(user_lines, topics, loop_bits, thread_bits, mood_line)
        if llm:
            return llm

    parts: list[str] = ["Here's your week in review."]
    if topics:
        parts.append(f"You talked most about {', '.join(topics[:3])}.")
    if loop_bits:
        parts.append(
            f"Still open: {loop_bits[0]}"
            + (f" and {len(loop_bits) - 1} more." if len(loop_bits) > 1 else ".")
        )
    if thread_bits:
        parts.append(f"Active threads include {', '.join(thread_bits[:3])}.")
    if mood_line:
        parts.append(mood_line)
    if len(parts) == 1:
        parts.append("It was a quiet week conversation-wise.")
    return " ".join(parts)


def _llm_digest(user_lines, topics, loops, threads, mood_line) -> Optional[str]:
    try:
        from openai import OpenAI
    except ImportError:
        return None
    sample = "\n".join(f"- {l[:200]}" for l in user_lines[-25:])
    prompt = (
        "Write a warm, concise 3-5 sentence weekly recap for a voice assistant to speak aloud. "
        "Mention recurring themes, any open commitments, and mood if relevant. No bullet lists.\n\n"
        f"Sample user lines:\n{sample or '(none)'}\n\n"
        f"Top tokens: {', '.join(topics) or 'none'}\n"
        f"Open loops: {', '.join(loops) or 'none'}\n"
        f"Threads: {', '.join(threads) or 'none'}\n"
        f"Mood note: {mood_line or 'none'}"
    )
    try:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.35,
        )
        reply = getattr(completion.choices[0].message, "content", None) or ""
        return reply.strip() or None
    except Exception:
        return None


def speak_weekly_digest(speak_fn) -> str:
    text = build_weekly_digest()
    speak_fn(text)
    try:
        from memory.episodic_memory import memory_append_turn

        memory_append_turn("note", f"weekly_digest:{text[:500]}")
    except Exception:
        pass
    return text


__all__ = ["build_weekly_digest", "speak_weekly_digest"]
