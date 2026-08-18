"""The one online-only piece of the RAG pipeline -- needs real Postgres + an embeddings endpoint; USE_LOCAL_RETRIEVAL=true is what keeps querying (not ingesting) credential-free."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import structlog

from core.config import settings
from core.db.engine import SessionLocal
from core.observability.logging import configure_logging
from modules.embedding.service import OpenAIEmbeddingService
from modules.ingestion.pipeline import ingest_directory

logger = structlog.get_logger(__name__)

# `cli.py` -> `ingestion` -> `modules` -> `src` -> `backend`.
DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[3] / "data" / "sample_corpus"


async def _run(directory: Path) -> int:
    embedding_service = OpenAIEmbeddingService()
    return await ingest_directory(
        directory, sessionmaker=SessionLocal, embedding_service=embedding_service
    )


def main() -> None:
    configure_logging(json_logs=settings.ENVIRONMENT != "local")
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CORPUS_DIR

    if not directory.is_dir():
        logger.error("ingestion.directory_not_found", directory=str(directory))
        raise SystemExit(1)

    chunk_count = asyncio.run(_run(directory))
    logger.info("ingestion.complete", directory=str(directory), chunk_count=chunk_count)
    if chunk_count == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
