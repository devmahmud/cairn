"""Chunk -> embed -> upsert. Documents matched by source path; re-ingesting replaces a document's chunks wholesale rather than appending duplicates."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modules.embedding.service import EmbeddingService
from modules.ingestion.chunking import chunk_text, split_into_sections
from modules.retrieval.models import Chunk, Document

logger = structlog.get_logger(__name__)

#: Bump when EMBEDDING_MODEL/EMBEDDING_DIMENSION changes in a way that invalidates stored vectors -- lets a migration re-embed only stale rows.
EMBEDDING_VERSION = "v1"
EMBEDDING_BATCH_SIZE = 64
_CORPUS_EXTENSIONS = frozenset({".md", ".txt"})


def _list_corpus_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in _CORPUS_EXTENSIONS
    )


async def ingest_directory(
    directory: Path,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    embedding_service: EmbeddingService,
) -> int:
    """Ingest every `.md`/`.txt` file under `directory`. Returns the total chunk count."""
    paths = await asyncio.to_thread(_list_corpus_files, directory)
    if not paths:
        logger.warning("ingestion.no_documents_found", directory=str(directory))
        return 0

    total_chunks = 0
    for path in paths:
        total_chunks += await _ingest_file(
            path, sessionmaker=sessionmaker, embedding_service=embedding_service
        )
    return total_chunks


async def _ingest_file(
    path: Path,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    embedding_service: EmbeddingService,
) -> int:
    source = str(path)
    text = await asyncio.to_thread(path.read_text, encoding="utf-8")

    # Every chunk from the same ## section shares one parent_id.
    chunks_with_parent: list[tuple[str, uuid.UUID]] = []
    for section in split_into_sections(text):
        parent_id = uuid.uuid4()
        chunks_with_parent.extend((content, parent_id) for content in chunk_text(section))
    if not chunks_with_parent:
        logger.warning("ingestion.empty_document_skipped", source=source)
        return 0

    vectors = await _embed_in_batches(
        [content for content, _ in chunks_with_parent], embedding_service
    )

    async with sessionmaker() as session:
        document = await _get_or_create_document(session, source=source, title=path.stem)
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        for (content, parent_id), vector in zip(chunks_with_parent, vectors, strict=True):
            session.add(
                Chunk(
                    id=uuid.uuid4(),
                    document_id=document.id,
                    parent_id=parent_id,
                    content=content,
                    embedding=vector,
                    embedding_version=EMBEDDING_VERSION,
                    metadata_={"source": path.name},
                )
            )
        await session.commit()

    logger.info(
        "ingestion.document_ingested",
        source=source,
        chunk_count=len(chunks_with_parent),
    )
    return len(chunks_with_parent)


async def _get_or_create_document(session: AsyncSession, *, source: str, title: str) -> Document:
    existing = (
        await session.execute(select(Document).where(Document.source == source))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    document = Document(id=uuid.uuid4(), title=title, source=source)
    session.add(document)
    await session.flush()
    return document


async def _embed_in_batches(
    chunks: list[str], embedding_service: EmbeddingService
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
        vectors.extend(await embedding_service.embed_documents(batch))
    return vectors
