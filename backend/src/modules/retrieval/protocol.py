"""One query() method is the entire surface rag.py depends on -- local fixture, pgvector hybrid, and reranked wrapper are all interchangeable behind it."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class RetrievalDoc(BaseModel):
    """score is comparable only within one call's results, never across retrievers. score_is_calibrated=True means score is a real ~[0,1] relevance signal (compare against abstain_score_threshold); False means an uncalibrated rank-fusion artifact (compare against the _unreranked threshold instead)."""

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
