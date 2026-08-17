"""Unit tests for `modules.retrieval.fixture.LocalFixtureRetrievalService` (BLUEPRINT.md §3.8)."""

from __future__ import annotations

from modules.retrieval.fixture import LocalFixtureRetrievalService


async def test_returns_relevant_passage_ranked_first() -> None:
    service = LocalFixtureRetrievalService()

    results = await service.query("What is the rate limit per minute?", top_k=3)

    assert results
    assert "rate limit" in results[0].content.lower()
    assert results[0].score > 0.0


async def test_results_are_sorted_by_score_descending() -> None:
    service = LocalFixtureRetrievalService()

    results = await service.query("How do I authenticate with an API key?", top_k=5)

    scores = [doc.score for doc in results]
    assert scores == sorted(scores, reverse=True)


async def test_unrelated_query_returns_no_results() -> None:
    service = LocalFixtureRetrievalService()

    results = await service.query("What is the airspeed velocity of an unladen swallow?", top_k=5)

    assert results == []


async def test_top_k_caps_result_count() -> None:
    service = LocalFixtureRetrievalService()

    results = await service.query("api key error rate limit webhook", top_k=2)

    assert len(results) <= 2
