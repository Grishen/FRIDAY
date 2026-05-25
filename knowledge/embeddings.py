"""Shared embeddings for Chroma + Postgres/pgvector backends."""

from __future__ import annotations

import os


def embedding_dimension() -> int:
    """Vector size for Postgres `vector(dim)` columns; must stay consistent across ingest + queries."""
    raw = os.environ.get("JARVIS_EMBEDDING_DIMENSION", "").strip()
    if raw.isdigit():
        return int(raw)
    if os.environ.get("OPENAI_API_KEY", "").strip():
        model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").lower()
        if "large" in model and "small" not in model:
            return int(os.environ.get("OPENAI_LARGE_EMBEDDING_DIM", "3072"))
        return int(os.environ.get("OPENAI_SMALL_EMBEDDING_DIM", "1536"))
    # sentence-transformers all-MiniLM-L6-v2
    return 384


_ST_MODEL = None


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding list per input string (same order)."""
    if not texts:
        return []
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return _embed_openai(texts)
    return _embed_sentence_transformer(texts)


def _embed_openai(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    out: list[list[float]] = []
    batch_size = int(os.environ.get("JARVIS_EMBED_BATCH_SIZE", "64"))
    i = 0
    while i < len(texts):
        slice_ = texts[i : i + batch_size]
        resp = client.embeddings.create(model=model, input=slice_)
        by_idx = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
        for row in by_idx:
            out.append(list(row.embedding))
        i += batch_size
    return out


def _embed_sentence_transformer(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer

    global _ST_MODEL  # noqa: PLW0603 — small caching pattern
    model_name = os.environ.get("ST_MODEL_NAME", "all-MiniLM-L6-v2")
    if _ST_MODEL is None:
        _ST_MODEL = SentenceTransformer(model_name)

    tensors = _ST_MODEL.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return tensors.tolist()  # type: ignore[union-attr]
