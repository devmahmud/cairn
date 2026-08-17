"""CLI entrypoint for `make ingest` (BLUEPRINT.md §3.8, §8 step 5).

    PYTHONPATH=src uv run python -m modules.ingestion.cli [directory]

(exactly what the Makefile's `ingest` target runs, `src/` as the import
root -- same convention `fastapi dev src/main.py` and pytest's
`pythonpath = ["src"]` already use, §8 step 2.) Defaults to
`backend/data/sample_corpus/`, the docs-assistant example's corpus.

This is the one piece of the RAG pipeline that's inherently online-only --
you can't chunk-and-embed a corpus with zero external dependencies, so it
needs a real Postgres and an embeddings endpoint reachable at
`OPENAI_BASE_URL`. That doesn't compromise the rest of the app's
offline-first stance (design principle #4): `USE_LOCAL_RETRIEVAL=true` is
what keeps *querying* (not ingesting) credential-free.
"""

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
