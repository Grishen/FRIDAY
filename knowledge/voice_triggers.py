"""Voice phrase matching for knowledge RAG — no heavy ML imports."""

from __future__ import annotations

import re

_RAG_PHRASES = (
    "knowledge base",
    "my knowledge base",
    "search my notes",
    "search my knowledge",
    "from my notes",
    "from my documents",
    "according to my documents",
    "ask my documents",
    "what do my documents say",
    "what does my knowledge say",
    "look in my notes",
)

_LEARN_PREFIXES = (
    "learn that ",
    "add to knowledge ",
    "save to knowledge ",
    "remember in knowledge ",
)


def wants_knowledge_lookup(q: str) -> bool:
    q = q.lower()
    return any(p in q for p in _RAG_PHRASES) or q.startswith("knowledge:")


def wants_learn_knowledge(q: str) -> bool:
    q = q.lower().strip()
    return any(q.startswith(p) for p in _LEARN_PREFIXES)


def extract_learn_text(q: str) -> str:
    q = q.lower().strip()
    for p in _LEARN_PREFIXES:
        if q.startswith(p):
            return q[len(p) :].strip(" .,!?:;")
    return ""


def extract_url(text: str) -> str:
    m = re.search(r"https?://\S+", text or "", flags=re.IGNORECASE)
    if not m:
        return ""
    return m.group(0).rstrip(".,);]")


def extract_kb_question(q: str) -> str:
    q = q.lower().strip()
    if q.startswith("knowledge:"):
        return q.split(":", 1)[1].strip()
    best = ""
    for p in _RAG_PHRASES:
        if p in q:
            tail = q.split(p, 1)[-1].strip(" :,.\t").strip()
            if len(tail) > len(best):
                best = tail
    best = re.sub(r"^(about|regarding|on|for)\s+", "", best, flags=re.I)
    return best.strip()
