"""Voice phrase matching for knowledge RAG — no heavy ML imports."""

from __future__ import annotations

import re

_RAG_PHRASES = (
    "knowledge base",
    "my knowledge base",
    "search my notes",
    "from my notes",
    "from my documents",
    "according to my documents",
    "ask my documents",
)


def wants_knowledge_lookup(q: str) -> bool:
    q = q.lower()
    return any(p in q for p in _RAG_PHRASES) or q.startswith("knowledge:")


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
