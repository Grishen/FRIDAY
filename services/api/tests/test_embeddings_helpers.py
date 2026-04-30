"""Pure helpers for embedding-distance scoring."""

from friday_api.providers.embeddings import cosine_distance_to_display_score


def test_cosine_distance_maps_endpoints_to_zero_one() -> None:
    assert cosine_distance_to_display_score(0.0) == 1.0  # identical
    assert cosine_distance_to_display_score(2.0) == 0.0  # opposite direction
    assert cosine_distance_to_display_score(1.0) == 0.5  # orthogonal-ish band


def test_cosine_distance_clamped() -> None:
    assert cosine_distance_to_display_score(-1.0) == 1.0
    assert cosine_distance_to_display_score(99.0) == 0.0
