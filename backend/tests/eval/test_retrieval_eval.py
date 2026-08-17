"""Retrieval eval -- golden query set scored with Recall@k / MRR / nDCG@k
(BLUEPRINT.md §3.8, §3.11, §8 step 10).

Deliberately **not** marked `eval` -- unlike the scenario/routing packs
(`test_scenario_eval.py`/`test_routing_eval.py`), this one needs no live
LLM: it runs entirely against `LocalFixtureRetrievalService`
(`modules/retrieval/fixture.py`, the same zero-dependency "Lumen" example-
product corpus the offline chat-graph tests use). That makes it part of the
"deterministic ... subset" `eval-gate.yml` actually gates on when
`config/behavior/retrieval.yaml` changes, and it also runs in a plain
`uv run pytest` (no `-m` filter needed to reach it).

The golden set below is intentionally scored against the *fixture's* own
crude keyword-overlap ranking, not against real embedding-model relevance
-- catching a regression in `LocalFixtureRetrievalService`'s scoring, or in
this repo's bundled corpus, is the point (§3.11: "catches RAG regressions").
A real deployment with `USE_LOCAL_RETRIEVAL=false` would want the same
golden queries re-run against `PgVectorHybridRetrievalService`/
`RerankedRetrieval` (`modules/retrieval/pgvector.py`/`reranker.py`) with a
real corpus and real thresholds -- `tests/eval/metrics.py`'s functions
already support that unchanged; only the fixture-vs-real service and the
expected-score thresholds would differ.
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.retrieval.fixture import LocalFixtureRetrievalService
from tests.eval.metrics import ndcg_at_k, recall_at_k, reciprocal_rank


@dataclass(frozen=True, slots=True)
class GoldenQuery:
    query: str
    relevant_document_id: str


# One `document_id` per golden query -- matches `modules/retrieval/fixture.py`'s
# `_FIXTURE_PASSAGES` (`lumen-getting-started` / `lumen-authentication` /
# `lumen-rate-limits` / `lumen-webhooks` / `lumen-errors`), covering every
# passage in the bundled corpus at least twice with independently-phrased
# queries.
GOLDEN_QUERIES: tuple[GoldenQuery, ...] = (
    GoldenQuery("How do I get an API key?", "lumen-getting-started"),
    GoldenQuery("What is the base URL for API requests?", "lumen-getting-started"),
    GoldenQuery("How do I set up my first request to the Lumen API?", "lumen-getting-started"),
    GoldenQuery("What happens if my Authorization header is missing?", "lumen-authentication"),
    GoldenQuery("Can I rotate my API key without downtime?", "lumen-authentication"),
    GoldenQuery(
        "What happens after I rotate my API key -- does the old one stop working immediately?",
        "lumen-authentication",
    ),
    GoldenQuery("What is the rate limit per minute?", "lumen-rate-limits"),
    GoldenQuery("What status code do I get when I exceed the rate limit?", "lumen-rate-limits"),
    GoldenQuery("How do I configure a webhook endpoint?", "lumen-webhooks"),
    GoldenQuery("What events can trigger a webhook?", "lumen-webhooks"),
    GoldenQuery("How many times does a failed webhook delivery get retried?", "lumen-webhooks"),
    GoldenQuery("What error code do I get for a validation failure?", "lumen-errors"),
    GoldenQuery("What error code means the resource was not found?", "lumen-errors"),
)

_TOP_K_FETCH = 5
_EVAL_K = 3

# Thresholds sit below what the current fixture corpus actually scores
# (Recall@3=1.00, MRR≈0.93, nDCG@3≈0.95 as of writing) -- enough headroom
# that adding a query or a fixture passage doesn't make this eval flaky,
# while still catching a real scoring regression.
_MIN_RECALL_AT_K = 0.85
_MIN_MRR = 0.80
_MIN_NDCG_AT_K = 0.80


async def test_golden_query_set_meets_retrieval_metric_thresholds() -> None:
    service = LocalFixtureRetrievalService()

    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    per_query_report: list[str] = []

    for golden in GOLDEN_QUERIES:
        docs = await service.query(golden.query, top_k=_TOP_K_FETCH)
        retrieved_ids = [doc.document_id for doc in docs]
        relevant = {golden.relevant_document_id}

        recall = recall_at_k(retrieved_ids, relevant, k=_EVAL_K)
        rr = reciprocal_rank(retrieved_ids, relevant)
        ndcg = ndcg_at_k(retrieved_ids, relevant, k=_EVAL_K)

        recalls.append(recall)
        reciprocal_ranks.append(rr)
        ndcgs.append(ndcg)
        per_query_report.append(
            f"  {golden.query!r} -> expected={golden.relevant_document_id!r} "
            f"retrieved={retrieved_ids} recall@{_EVAL_K}={recall:.2f} rr={rr:.2f} "
            f"ndcg@{_EVAL_K}={ndcg:.2f}"
        )

    mean_recall = sum(recalls) / len(recalls)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    mean_ndcg = sum(ndcgs) / len(ndcgs)
    report = "\n".join(per_query_report)

    assert mean_recall >= _MIN_RECALL_AT_K, (
        f"Recall@{_EVAL_K}={mean_recall:.2f} < {_MIN_RECALL_AT_K}\n{report}"
    )
    assert mrr >= _MIN_MRR, f"MRR={mrr:.2f} < {_MIN_MRR}\n{report}"
    assert mean_ndcg >= _MIN_NDCG_AT_K, (
        f"nDCG@{_EVAL_K}={mean_ndcg:.2f} < {_MIN_NDCG_AT_K}\n{report}"
    )


async def test_every_golden_document_id_actually_exists_in_the_fixture_corpus() -> None:
    """Guards the golden set itself -- a typo'd `document_id` above would
    otherwise just silently score 0 on that one query rather than failing
    loudly."""
    service = LocalFixtureRetrievalService()
    all_document_ids: set[str] = set()
    for golden in GOLDEN_QUERIES:
        docs = await service.query(golden.query, top_k=_TOP_K_FETCH)
        all_document_ids.update(doc.document_id for doc in docs)

    expected_ids = {golden.relevant_document_id for golden in GOLDEN_QUERIES}
    missing = expected_ids - all_document_ids
    assert not missing, f"golden document ids never returned by the fixture corpus: {missing}"
