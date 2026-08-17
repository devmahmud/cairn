"""Cross-encoder reranking behind the `RetrievalService` Protocol (BLUEPRINT.md §3.8).

`RerankedRetrieval` wraps any base `RetrievalService` (in practice,
`PgVectorHybridRetrievalService`): overfetch → score every candidate with a
self-hosted cross-encoder (`bge-reranker-v2-m3` by default, Apache-2.0) →
take the top-k → dedupe by `parent_id`. The reranker itself is called over
HTTP against a Text-Embeddings-Inference/vLLM-style `/rerank` endpoint
(`{"query", "texts"} -> [{"index", "score"}, ...]`) -- the same
"self-hosted, `OPENAI_BASE_URL`-style swap point" pattern as `agents/llm.py`
and `modules/embedding/service.py`, just without an OpenAI-compatible route
for cross-encoder rerank specifically.

Degrades gracefully in both directions (design principle #4): no
`RERANKER_BASE_URL` configured, or a reachable-but-erroring reranker at
request time, both fall back to the *unreranked* fused candidates rather
than failing the turn -- a worse-ranked answer beats no answer.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
import structlog

from modules.retrieval.protocol import RetrievalDoc, RetrievalService

logger = structlog.get_logger(__name__)

# "top-k → dedupe by parent_id" (§3.8): overfetch this many candidates from
# the base service before scoring, so the reranker sees more than exactly
# `top_k` and dedup doesn't starve the final result set.
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
        top = [doc.model_copy(update={"score": score}) for doc, score in reranked[:top_k]]
        return _dedupe_by_parent(top)


def _dedupe_by_parent(docs: list[RetrievalDoc]) -> list[RetrievalDoc]:
    """Keep the first (highest-scored) chunk per `parent_id`; keep every
    chunk with no `parent_id` (nothing to dedupe it against)."""
    seen_parents: set[str] = set()
    deduped: list[RetrievalDoc] = []
    for doc in docs:
        if doc.parent_id is not None:
            if doc.parent_id in seen_parents:
                continue
            seen_parents.add(doc.parent_id)
        deduped.append(doc)
    return deduped
