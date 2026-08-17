"""Ranking metrics for the retrieval eval (BLUEPRINT.md §3.8, §3.11, §8 step 10).

Not a `test_*.py` file -- same "importable support module" pattern as
`tests/unit/fakes.py`. Binary relevance only (a candidate id is relevant or
it isn't) -- the golden query set in `test_retrieval_eval.py` never needs
graded relevance, and binary keeps these three functions trivially testable
in isolation (`tests/unit/test_eval_metrics.py`) with hand-computed
expected values.

All three take the same shape of arguments: `retrieved_ids` (already
ranked, best first -- exactly what `RetrievalService.query()` returns) and
`relevant_ids` (the query's gold set, unordered). None of them are specific
to this template's `RetrievalDoc`/pgvector -- swapping in a real
`PgVectorHybridRetrievalService`/`RerankedRetrieval` golden-set run later
would reuse these unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of `relevant_ids` that appear anywhere in the top `k` of `retrieved_ids`."""
    if not relevant_ids:
        raise ValueError(
            "relevant_ids must be non-empty -- a query with no gold answer isn't scoreable."
        )
    hits = len(set(retrieved_ids[:k]) & relevant_ids)
    return hits / len(relevant_ids)


def reciprocal_rank(retrieved_ids: Sequence[str], relevant_ids: set[str]) -> float:
    """`1 / rank` of the first relevant id in `retrieved_ids` (1-indexed), or `0.0` if none appear."""
    for rank, candidate_id in enumerate(retrieved_ids, start=1):
        if candidate_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    """Normalized DCG@k with binary gains -- `1.0` iff every relevant id is packed into the best possible ranks."""
    if not relevant_ids:
        raise ValueError(
            "relevant_ids must be non-empty -- a query with no gold answer isn't scoreable."
        )
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, candidate_id in enumerate(retrieved_ids[:k], start=1)
        if candidate_id in relevant_ids
    )
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0
