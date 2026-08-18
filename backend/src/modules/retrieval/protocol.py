"""The `RetrievalService` Protocol + its result shape (BLUEPRINT.md §3.8).

One `query()` method is the entire surface `agents/chat/nodes/rag.py`
depends on -- everything downstream of it (local fixture, pgvector hybrid,
reranked wrapper) is interchangeable behind this Protocol, matching design
principle #4 ("offline-first ... every external dependency degrades to a
local/no-op default").
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class RetrievalDoc(BaseModel):
    """One retrieved passage, ready to ground an answer and cite a source.

    `score` is retriever-specific and only comparable *within* one call's
    results, never across retrievers: a raw cosine similarity, an RRF-fused
    rank score, or (once `RerankedRetrieval` wraps the base service) a
    cross-encoder relevance score in roughly `[0, 1]`. `agents/chat/nodes/rag.py`'s
    abstention check only ever reads `score` off the *final* (possibly
    reranked) result list, never mixes retrievers' scores together.

    `score_is_calibrated` tells that abstention check which threshold applies
    (§3.8): `True` means `score` is a real, roughly-`[0, 1]` relevance signal
    -- a cross-encoder reranker score, or the local fixture's keyword-overlap
    ratio -- comparable against `config/behavior/retrieval.yaml`'s
    `abstain_score_threshold`. `False` means `score` is only a rank-fusion
    artifact (`PgVectorHybridRetrievalService`'s bare RRF score, `k=60` tops
    out around `0.033`) with no absolute-quality meaning, and must be
    compared against the separately-calibrated `abstain_score_threshold_unreranked`
    instead. Defaults to `True` so a custom `RetrievalService` that never sets
    it keeps today's behavior (the reranked-scale threshold) rather than
    silently switching scales underneath it.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    parent_id: str | None = None
    content: str
    source: str | None = None
    score: float
    score_is_calibrated: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class RetrievalService(Protocol):
    async def query(
        self, text: str, top_k: int, filters: dict[str, Any] | None = None
    ) -> list[RetrievalDoc]: ...
