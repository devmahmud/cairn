"""Unit tests for `modules.retrieval.reranker` (BLUEPRINT.md §3.8).

`RerankedRetrieval`'s degrade-gracefully-on-failure behavior and the
`_dedupe_by_parent` helper it applies after truncating to `top_k` -- both
pure logic, no HTTP involved (`HTTPCrossEncoderReranker` itself is a thin
wrapper over `httpx`, not worth mocking a fake server for here).
"""

from __future__ import annotations

from typing import Any

from modules.retrieval.protocol import RetrievalDoc, RetrievalService
from modules.retrieval.reranker import RerankedRetrieval


class _FakeInnerRetrieval:
    def __init__(self, docs: list[RetrievalDoc]) -> None:
        self._docs = docs

    async def query(
        self, text: str, top_k: int, filters: dict[str, Any] | None = None
    ) -> list[RetrievalDoc]:
        return self._docs[:top_k]


class _FailingReranker:
    async def score(self, query: str, documents: list[str]) -> list[float]:
        raise RuntimeError("reranker endpoint unreachable")


class _ReversingReranker:
    """Scores the *last* candidate highest, so a test can see the reorder happen."""

    async def score(self, query: str, documents: list[str]) -> list[float]:
        return [float(index) for index in range(len(documents))]


def _doc(doc_id: str, *, parent_id: str | None = None, score: float = 0.5) -> RetrievalDoc:
    return RetrievalDoc(
        id=doc_id,
        document_id="doc-1",
        parent_id=parent_id,
        content=f"content {doc_id}",
        score=score,
    )


async def test_falls_back_to_unreranked_candidates_when_reranker_fails() -> None:
    docs = [_doc("a"), _doc("b"), _doc("c")]
    inner: RetrievalService = _FakeInnerRetrieval(docs)
    service = RerankedRetrieval(inner, _FailingReranker())

    results = await service.query("anything", top_k=2)

    assert [doc.id for doc in results] == ["a", "b"]


async def test_reorders_candidates_by_reranker_score() -> None:
    docs = [_doc("a"), _doc("b"), _doc("c")]
    inner: RetrievalService = _FakeInnerRetrieval(docs)
    service = RerankedRetrieval(inner, _ReversingReranker())

    results = await service.query("anything", top_k=3)

    # `_ReversingReranker` scores index 0 lowest, last index highest --
    # the last candidate should now rank first.
    assert [doc.id for doc in results] == ["c", "b", "a"]


async def test_dedupes_by_parent_id_after_truncating_to_top_k() -> None:
    docs = [
        _doc("a", parent_id="section-1", score=3.0),
        _doc("b", parent_id="section-1", score=2.0),
        _doc("c", parent_id="section-2", score=1.0),
    ]
    inner: RetrievalService = _FakeInnerRetrieval(docs)

    class _IdentityReranker:
        async def score(self, query: str, documents: list[str]) -> list[float]:
            return [3.0, 2.0, 1.0]

    service = RerankedRetrieval(inner, _IdentityReranker())

    results = await service.query("anything", top_k=2)

    # top_k=2 would naively keep "a" and "b" -- both share `parent_id`
    # "section-1", so dedup collapses them to just "a" (the higher-scored
    # one).
    assert [doc.id for doc in results] == ["a"]


async def test_empty_candidates_short_circuits_without_calling_reranker() -> None:
    inner: RetrievalService = _FakeInnerRetrieval([])
    service = RerankedRetrieval(inner, _FailingReranker())

    results = await service.query("anything", top_k=5)

    assert results == []
