"""Composite Q&A: blend memory + local knowledge + web + Wikipedia into one answer.

Used by the "ask everything" / "deep dive" voice path and exposed as a brain tool.
Gracefully degrades when individual sources are unavailable.
"""

from __future__ import annotations

import os
from typing import Any


_MAX_CTX_CHARS = 9000


def _safe(call, default):
    try:
        return call()
    except Exception:
        return default


def _gather_memory(question: str) -> str:
    try:
        from memory.episodic_memory import memory_build_context_for_prompt

        return memory_build_context_for_prompt(query=question, max_chars=2500)
    except Exception:
        return ""


def _gather_local_docs(question: str) -> tuple[str, list[str]]:
    try:
        from knowledge import fs_index
        from knowledge.rag_store import (
            _collection,  # type: ignore[attr-defined]
            _collection_document_count,  # type: ignore[attr-defined]
            _retrieve_hybrid,  # type: ignore[attr-defined]
            _vector_backend,  # type: ignore[attr-defined]
            sync_knowledge_folder,
        )
    except Exception:
        return "", []

    try:
        sync_knowledge_folder()
    except Exception:
        pass

    backend = _safe(_vector_backend, "chroma")
    chunks: list[str] = []
    sources: list[str] = []
    if backend == "postgres":
        try:
            from knowledge import postgres_kb
            from knowledge.retrieval import hybrid_rerank

            raw_chunks, raw_sources = postgres_kb.postgres_retrieve(question, k=10)
            chunks, sources = hybrid_rerank(question, raw_chunks, raw_sources, top_k=5)
        except Exception:
            chunks, sources = [], []
    else:
        try:
            col = _collection()
            if _collection_document_count(col) > 0:
                chunks, sources = _retrieve_hybrid(question, col, pool_k=10, top_k=5)
        except Exception:
            chunks, sources = [], []

    if not chunks:
        return "", []
    blob = "\n\n---\n\n".join(f"[{sources[i]}]\n{c}" for i, c in enumerate(chunks))
    return blob[:3500], list(dict.fromkeys(sources))


def _gather_web(question: str, *, limit: int = 4) -> tuple[str, list[str]]:
    try:
        from web_search import search_web
    except Exception:
        return "", []
    results = search_web(question, limit=limit)
    if not results:
        return "", []
    lines: list[str] = []
    urls: list[str] = []
    for r in results:
        title = r.get("title") or ""
        url = r.get("url") or ""
        snippet = r.get("snippet") or ""
        if url:
            urls.append(url)
        lines.append(f"- {title} — {snippet} ({url})")
    return "Web results:\n" + "\n".join(lines), urls


def _gather_wikipedia(question: str) -> str:
    try:
        from jarvis_actions import wikipedia_summary
    except Exception:
        return ""
    text = wikipedia_summary(question, sentences=4)
    if not text:
        return ""
    if text.lower().startswith("wikipedia lookup failed") or text.lower().startswith(
        "wikipedia could not"
    ):
        return ""
    return "Wikipedia excerpt:\n" + text


def _synthesize(question: str, memory_ctx: str, docs_ctx: str, web_ctx: str, wiki_ctx: str) -> str:
    """Have the LLM blend gathered sources into a natural human answer."""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        # Fallback: simple concatenation, lightly trimmed.
        parts = [p for p in (docs_ctx, wiki_ctx, web_ctx, memory_ctx) if p]
        if not parts:
            return "I could not gather anything useful from memory, docs, web, or Wikipedia, Sir."
        return ("Sir, here is what I gathered: " + " | ".join(parts))[:1800]

    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    except Exception as exc:  # noqa: BLE001
        return f"Synthesis unavailable: {exc}"

    try:
        from jarvis_brain import brain_system_instructions

        persona = brain_system_instructions()
    except Exception:
        persona = "You are a helpful voice assistant. Be natural, concise, and grounded."

    sys_text = (
        persona
        + "\n\nYou are answering using MULTIPLE GROUNDING SOURCES. "
        "Prefer local docs and memory when they directly address the question; "
        "use web/Wikipedia for live or general knowledge. "
        "If sources disagree, mention the disagreement briefly. "
        "If nothing is relevant, say so plainly. Cite source labels (file names, "
        "Wikipedia, or 'web') in passing — do NOT dump URLs in the spoken answer. "
        "Keep it natural and under ~10 sentences for speech."
    )
    ctx_parts: list[str] = []
    if memory_ctx:
        ctx_parts.append("MEMORY:\n" + memory_ctx)
    if docs_ctx:
        ctx_parts.append("LOCAL DOCS:\n" + docs_ctx)
    if wiki_ctx:
        ctx_parts.append(wiki_ctx)
    if web_ctx:
        ctx_parts.append(web_ctx)
    if not ctx_parts:
        return "I could not gather anything useful from memory, docs, web, or Wikipedia, Sir."

    context_blob = "\n\n".join(ctx_parts)[:_MAX_CTX_CHARS]
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_text},
                {
                    "role": "user",
                    "content": f"QUESTION:\n{question}\n\nGROUNDING SOURCES:\n{context_blob}",
                },
            ],
            temperature=0.35,
        )
    except Exception as exc:  # noqa: BLE001
        return f"Synthesis failed: {exc}"
    msg = getattr(completion.choices[0].message, "content", None) or ""
    return msg.strip() or "I formed no spoken answer from those sources, Sir."


def unified_ask(question: str, *, use_web: bool = True, use_wiki: bool = True) -> dict[str, Any]:
    """
    Pull from memory, local docs, web search, and Wikipedia (best-effort each),
    then synthesize a single natural reply.

    Returns ``{"reply": str, "sources": list[str]}``. ``sources`` is a small
    list of doc filenames or URLs that contributed (for optional ingestion).
    """
    q = (question or "").strip()
    if not q:
        return {"reply": "Please give me a question, Sir.", "sources": []}

    memory_ctx = _gather_memory(q)
    docs_ctx, doc_sources = _gather_local_docs(q)
    web_ctx, web_urls = (_gather_web(q) if use_web else ("", []))
    wiki_ctx = _gather_wikipedia(q) if use_wiki else ""

    reply = _synthesize(q, memory_ctx, docs_ctx, web_ctx, wiki_ctx)
    sources = list(dict.fromkeys(list(doc_sources) + list(web_urls)))[:8]
    return {"reply": reply, "sources": sources}


__all__ = ["unified_ask"]
