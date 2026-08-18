"""RerankedRetrieval wraps a base RetrievalService with cross-encoder reranking; degrades to unreranked results (never fails the turn) if no reranker is configured or reachable."""

from __future__ import annotations

from typing import Any, Protocol

import httpx
import structlog

from modules.retrieval.protocol import RetrievalDoc, RetrievalService

logger = structlog.get_logger(__name__)

# Overfetch beyond top_k so dedup by parent_id doesn't starve the final result set.
DEFAULT_RERANK_OVERFETCH_MULTIPLIER = 3.0
DEFAULT_RERANK_TIMEOUT_SECONDS = 10.0


class Reranker(Protocol):
    async def score(self, query: str, documents: list[str]) -> list[float]: ...


class HTTPCrossEncoderReranker:
    """`Reranker` over a self-hosted TEI/vLLM-style `POST {base_url}/rerank`."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = DEFAULT_RERANK_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/rerank",
                json={"model": self._model, "query": query, "texts": documents},
            )
            response.raise_for_status()
            payload = response.json()

        results: list[dict[str, Any]] = payload if isinstance(payload, list) else payload["results"]
        scores = [0.0] * len(documents)
        for item in results:
            scores[item["index"]] = float(item["score"])
        return scores


class RerankedRetrieval:
    """`RetrievalService` wrapper: overfetch the inner service, then rerank."""

    def __init__(
        self,
        inner: RetrievalService,
        reranker: Reranker,
        *,
        overfetch_multiplier: float = DEFAULT_RERANK_OVERFETCH_MULTIPLIER,
    ) -> None:
        self._inner = inner
        self._reranker = reranker
        self._overfetch_multiplier = overfetch_multiplier

    async def query(
        self, text: str, top_k: int, filters: dict[str, Any] | None = None
    ) -> list[RetrievalDoc]:
        overfetch = max(top_k, round(top_k * self._overfetch_multiplier))
        candidates = await self._inner.query(text, overfetch, filters)
        if not candidates:
            return []

        try:
            scores = await self._reranker.score(text, [doc.content for doc in candidates])
        except Exception:
            logger.warning(
                "reranker.unavailable_falling_back_to_unreranked",
                candidate_count=len(candidates),
                exc_info=True,
            )
            return _dedupe_by_parent(candidates)[:top_k]

        reranked = sorted(
            zip(candidates, scores, strict=True), key=lambda pair: pair[1], reverse=True
        )
        # Marks calibrated=True: this is now a real cross-encoder score in ~[0, 1], not the inner service's rank-fusion artifact.
        top = [
            doc.model_copy(update={"score": score, "score_is_calibrated": True})
            for doc, score in reranked[:top_k]
        ]
        return _dedupe_by_parent(top)


def _dedupe_by_parent(docs: list[RetrievalDoc]) -> list[RetrievalDoc]:
    """Keeps the first chunk per parent_id -- callers must pass docs pre-sorted by priority."""
    seen_parents: set[str] = set()
    deduped: list[RetrievalDoc] = []
    for doc in docs:
        if doc.parent_id is not None:
            if doc.parent_id in seen_parents:
                continue
            seen_parents.add(doc.parent_id)
        deduped.append(doc)
    return deduped
