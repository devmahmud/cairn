"""DI container's retrieval_service provider is this function partially applied to settings; unit tests call it directly with use_local=True for the zero-dep fixture path."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from modules.embedding.service import EmbeddingService
from modules.retrieval.fixture import LocalFixtureRetrievalService
from modules.retrieval.pgvector import PgVectorHybridRetrievalService
from modules.retrieval.protocol import RetrievalService
from modules.retrieval.reranker import HTTPCrossEncoderReranker, RerankedRetrieval

logger = structlog.get_logger(__name__)


def build_retrieval_service(
    *,
    use_local: bool,
    rerank: bool,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    embedding_service: EmbeddingService | None = None,
    reranker_base_url: str = settings.RERANKER_BASE_URL,
    reranker_model: str = settings.RERANKER_MODEL,
) -> RetrievalService:
    if use_local:
        return LocalFixtureRetrievalService()

    if sessionmaker is None or embedding_service is None:
        raise ValueError(
            "build_retrieval_service(use_local=False, ...) needs both "
            "`sessionmaker` and `embedding_service` to build "
            "PgVectorHybridRetrievalService."
        )

    hybrid: RetrievalService = PgVectorHybridRetrievalService(
        sessionmaker=sessionmaker, embedding_service=embedding_service
    )
    if not rerank:
        return hybrid

    if not reranker_base_url:
        # RERANK_ENABLED=true with no RERANKER_BASE_URL shouldn't crash retrieval -- serve unreranked results and warn once instead of raising every query.
        logger.warning(
            "retrieval.rerank_enabled_but_no_reranker_base_url_configured",
            hint="Set RERANKER_BASE_URL to a self-hosted bge-reranker-v2-m3 "
            "(or Qwen3-Reranker) endpoint, or set RERANK_ENABLED=false.",
        )
        return hybrid

    reranker = HTTPCrossEncoderReranker(base_url=reranker_base_url, model=reranker_model)
    return RerankedRetrieval(hybrid, reranker)
