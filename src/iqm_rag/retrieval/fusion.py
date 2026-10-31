"""Reciprocal rank fusion: merge several rankings into one without comparing their scores (which are on different scales)."""

from typing import Sequence

RRF_K = 60  # the constant from the original RRF paper; larger values flatten the difference between ranks


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Each item scores the sum of 1 / (k + rank) over the rankings that contain it. Returns (id, score), best first.

    Ties are broken by the order in which items first appear, so the result is repeatable.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: -pair[1])  # sorted is stable, so insertion order breaks ties
