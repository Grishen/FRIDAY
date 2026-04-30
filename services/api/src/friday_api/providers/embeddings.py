"""Embedding provider registry (mock now; wire OpenAI/Azure later)."""

from __future__ import annotations

from functools import lru_cache

from friday_api.config import get_settings
from friday_api.providers.mock import MockEmbeddingProvider


@lru_cache
def get_embedding_provider() -> MockEmbeddingProvider:
    settings = get_settings()
    return MockEmbeddingProvider(dimensions=settings.embedding_dimensions)


def cosine_distance_to_display_score(distance: float) -> float:
    """Map pgvector cosine distance (≈0 identical … ≈2 opposite) to [0,1] UI score.

    Matches ``(cosine_similarity + 1) / 2`` when distance is ``1 - cosine_similarity``.
    """

    return max(0.0, min(1.0, (2.0 - float(distance)) / 2.0))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity mapped to ~[0, 1] for ranking mock vectors."""
    import math

    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    aa, bb = a[:n], b[:n]
    dot = sum(x * y for x, y in zip(aa, bb, strict=True))
    na = math.sqrt(sum(x * x for x in aa))
    nb = math.sqrt(sum(y * y for y in bb))
    if na == 0 or nb == 0:
        return 0.0
    # Cosine similarity normally [-1, 1]; normalize to [0,1] for UX
    raw = dot / (na * nb)
    return max(0.0, min(1.0, (raw + 1.0) / 2.0))


def to_embedding_list(raw: object) -> list[float]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [float(x) for x in raw]
    return list(raw)  # pragma: no cover
