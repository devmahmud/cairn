"""PgVectorHybridRetrievalService -- fuses lexical (Postgres FTS) and vector (HNSW) candidates via Reciprocal Rank Fusion."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.embedding.service import EmbeddingService
from modules.retrieval.models import Chunk
from modules.retrieval.protocol import RetrievalDoc

# RRF's standard smoothing constant (Cormack et al., 2009); large enough that a rank-1 hit doesn't drown out a rank-2/3 hit.
DEFAULT_RRF_K = 60
# Each list overfetches top_k * multiplier rows before fusion narrows back, so a passage weak in one signal can still fuse in.
DEFAULT_OVERFETCH_MULTIPLIER = 4.0


class PgVectorHybridRetrievalService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        embedding_service: EmbeddingService,
        overfetch_multiplier: float = DEFAULT_OVERFETCH_MULTIPLIER,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._embedding_service = embedding_service
        self._overfetch_multiplier = overfetch_multiplier
        self._rrf_k = rrf_k

    async def query(
        self, text: str, top_k: int, filters: dict[str, Any] | None = None
    ) -> list[RetrievalDoc]:
        overfetch = max(top_k, round(top_k * self._overfetch_multiplier))
        document_id = _parse_document_id_filter(filters)
        query_embedding = await self._embedding_service.embed_query(text)

        # Short read-only unit of work -- never the request-scoped REST session, never held across an LLM call.
        async with self._sessionmaker() as session:
            await _configure_session(session, filtered=document_id is not None)
            vector_rows = await self._vector_search(
                session, query_embedding, overfetch, document_id
            )
            lexical_rows = await self._lexical_search(session, text, overfetch, document_id)

        fused = _reciprocal_rank_fusion(vector_rows, lexical_rows, k=self._rrf_k)
        return [_to_retrieval_doc(chunk, score) for chunk, score in fused[:top_k]]

    async def _vector_search(
        self,
        session: AsyncSession,
        query_embedding: list[float],
        limit: int,
        document_id: uuid.UUID | None,
    ) -> list[Chunk]:
        stmt = (
            sa.select(Chunk)
            .where(Chunk.embedding.is_not(None))
            .order_by(Chunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        if document_id is not None:
            stmt = stmt.where(Chunk.document_id == document_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _lexical_search(
        self,
        session: AsyncSession,
        query_text: str,
        limit: int,
        document_id: uuid.UUID | None,
    ) -> list[Chunk]:
        # plainto_tsquery, not websearch_to_tsquery, keeps the operator surface minimal for a template; swap it if real BM25 matters.
        tsquery = sa.func.plainto_tsquery("english", query_text)
        stmt = (
            sa.select(Chunk)
            .where(Chunk.content_tsv.op("@@")(tsquery))
            .order_by(sa.func.ts_rank(Chunk.content_tsv, tsquery).desc())
            .limit(limit)
        )
        if document_id is not None:
            stmt = stmt.where(Chunk.document_id == document_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _configure_session(session: AsyncSession, *, filtered: bool) -> None:
    """SET LOCAL scopes both GUCs to this transaction; iterative_scan avoids HNSW recall collapsing when combined with a WHERE filter."""
    await session.execute(sa.text("SET LOCAL hnsw.ef_search = 40"))
    if filtered:
        await session.execute(sa.text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))


def _parse_document_id_filter(filters: dict[str, Any] | None) -> uuid.UUID | None:
    if not filters:
        return None
    raw = filters.get("document_id")
    if raw is None:
        return None
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


def _reciprocal_rank_fusion(
    vector_rows: list[Chunk], lexical_rows: list[Chunk], *, k: int
) -> list[tuple[Chunk, float]]:
    scores: dict[uuid.UUID, float] = {}
    chunks_by_id: dict[uuid.UUID, Chunk] = {}
    for ranked_list in (vector_rows, lexical_rows):
        for rank, chunk in enumerate(ranked_list, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (k + rank)
            chunks_by_id[chunk.id] = chunk
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    return [(chunks_by_id[chunk_id], score) for chunk_id, score in ranked]


def _to_retrieval_doc(chunk: Chunk, score: float) -> RetrievalDoc:
    metadata = dict(chunk.metadata_ or {})
    source = metadata.get("source")
    return RetrievalDoc(
        id=str(chunk.id),
        document_id=str(chunk.document_id),
        parent_id=str(chunk.parent_id) if chunk.parent_id is not None else None,
        content=chunk.content,
        source=str(source) if source is not None else None,
        score=score,
        # RRF-scale score, not calibrated -- rag.py's abstention check would misfire against a reranker-scale threshold if True.
        score_is_calibrated=False,
        metadata=metadata,
    )
