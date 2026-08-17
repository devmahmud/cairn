"""Unit tests for `tests.eval.metrics` (BLUEPRINT.md §3.8, §3.11, §8 step 10).

Hand-computed expected values, not derived from the metric functions
themselves -- the point is to catch a broken formula, not to restate it.
"""

from __future__ import annotations

import math

import pytest

from tests.eval.metrics import ndcg_at_k, recall_at_k, reciprocal_rank

_RETRIEVED = ["a", "b", "c", "d"]


def test_recall_at_k_counts_a_hit_anywhere_in_the_window() -> None:
    assert recall_at_k(_RETRIEVED, {"b"}, k=3) == 1.0
    assert recall_at_k(_RETRIEVED, {"b"}, k=1) == 0.0


def test_recall_at_k_averages_over_multiple_relevant_ids() -> None:
    # Only "b" of {"b", "d"} falls inside the top 3 -- half credit.
    assert recall_at_k(_RETRIEVED, {"b", "d"}, k=3) == 0.5


def test_recall_at_k_rejects_an_empty_gold_set() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        recall_at_k(_RETRIEVED, set(), k=3)


def test_reciprocal_rank_of_the_first_hit() -> None:
    assert reciprocal_rank(_RETRIEVED, {"b"}) == pytest.approx(0.5)
    assert reciprocal_rank(_RETRIEVED, {"a", "c"}) == pytest.approx(1.0)


def test_reciprocal_rank_is_zero_when_nothing_relevant_is_retrieved() -> None:
    assert reciprocal_rank(_RETRIEVED, {"z"}) == 0.0


def test_ndcg_at_k_is_perfect_when_the_only_relevant_id_ranks_first() -> None:
    assert ndcg_at_k(_RETRIEVED, {"a"}, k=3) == pytest.approx(1.0)


def test_ndcg_at_k_discounts_a_lower_rank() -> None:
    # DCG = 1/log2(3) (rank 2); IDCG = 1/log2(2) (best possible: rank 1).
    expected = (1.0 / math.log2(3)) / (1.0 / math.log2(2))
    assert ndcg_at_k(_RETRIEVED, {"b"}, k=3) == pytest.approx(expected)


def test_ndcg_at_k_is_zero_when_nothing_relevant_falls_within_k() -> None:
    assert ndcg_at_k(_RETRIEVED, {"d"}, k=2) == 0.0


def test_ndcg_at_k_rejects_an_empty_gold_set() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ndcg_at_k(_RETRIEVED, set(), k=3)
