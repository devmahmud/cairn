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
    """

    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    parent_id: str | None = None
    content: str
    source: str | None = None
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class RetrievalService(Protocol):
    async def query(
        self, text: str, top_k: int, filters: dict[str, Any] | None = None
    ) -> list[RetrievalDoc]: ...
