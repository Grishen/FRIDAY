"""Hybrid retrieval helpers for local knowledge RAG."""

from __future__ import annotations

import re
from typing import Iterable

_TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "what",
    "when",
    "where",
    "which",
    "about",
    "your",
    "have",
    "does",
    "into",
}


def _tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text or "")
        if len(t) > 2 and t.lower() not in _STOP
    }


def expand_query(question: str) -> set[str]:
    """Lightweight query expansion for better recall on local docs."""
    base = _tokens(question)
    expanded = set(base)
    q = (question or "").lower()
    if "how" in q and "work" in q:
        expanded.update({"setup", "install", "configure", "usage", "steps"})
    if "error" in q or "fail" in q:
        expanded.update({"troubleshoot", "fix", "issue", "exception"})
    if "memory" in q:
        expanded.update({"remember", "profile", "note", "event"})
    return expanded


def hybrid_rerank(
    question: str,
    chunks: list[str],
    sources: list[str],
    *,
    top_k: int = 6,
) -> tuple[list[str], list[str]]:
    """
    Re-rank vector hits with lexical overlap so exact keyword matches
    (names, commands, env vars) surface even when embeddings are fuzzy.
    """
    if not chunks:
        return [], []

    q_tokens = expand_query(question)
    scored: list[tuple[float, int, str, str]] = []
    for idx, chunk in enumerate(chunks):
        src = sources[idx] if idx < len(sources) else "unknown"
        c_tokens = _tokens(chunk)
        overlap = len(q_tokens.intersection(c_tokens))
        # Earlier vector rank still matters; overlap boosts exact matches.
        vector_rank_bonus = max(0.0, (len(chunks) - idx) / max(1, len(chunks)))
        score = overlap * 2.0 + vector_rank_bonus
        if src.lower() in (question or "").lower():
            score += 1.5
        scored.append((score, idx, chunk, src))

    scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)
    picked = scored[: max(1, top_k)]
    out_chunks = [row[2] for row in picked]
    out_sources = [row[3] for row in picked]
    return out_chunks, out_sources


def merge_unique_results(
    primary_chunks: Iterable[str],
    primary_sources: Iterable[str],
    secondary_chunks: Iterable[str],
    secondary_sources: Iterable[str],
    *,
    max_total: int = 10,
) -> tuple[list[str], list[str]]:
    """Merge two retrieval lists while preserving order and deduplicating."""
    seen: set[str] = set()
    chunks: list[str] = []
    sources: list[str] = []

    def _add(c: str, s: str) -> None:
        key = c.strip()[:240]
        if not key or key in seen:
            return
        seen.add(key)
        chunks.append(c)
        sources.append(s)

    for c, s in zip(primary_chunks, primary_sources):
        _add(c, s)
    for c, s in zip(secondary_chunks, secondary_sources):
        _add(c, s)
        if len(chunks) >= max_total:
            break
    return chunks, sources
