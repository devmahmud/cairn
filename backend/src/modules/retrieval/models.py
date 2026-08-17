"""ORM models for the RAG corpus (BLUEPRINT.md §3.3, §3.8).

Maps onto the `documents` / `chunks` tables the initial migration already
created (`alembic/versions/7fb143f2218e_initial_schema.py`) -- this file
does not create or alter schema. Owned by `retrieval/` (the read path, and a
required runtime dependency of every chat turn) rather than `ingestion/`
(a batch/CLI-only write path, §8 step 5) -- `modules/ingestion/pipeline.py`
imports `Document`/`Chunk` from here rather than the other way around.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base

# Must match `core.config.Settings.EMBEDDING_DIMENSION` *and* the initial
# migration's own `EMBEDDING_DIMENSION` constant, for the same reason
# `modules/conversations/models.py` hardcodes it: a column-width change
# needs its own migration, not just an `.env` edit (BLUEPRINT.md §3.3).
EMBEDDING_DIMENSION = 1024


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str | None] = mapped_column(Text())
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    # Dedupe key for reranked results sharing a source section (§3.8:
    # "dedupe by parent_id"); null for a chunk that has no parent.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSION))
    embedding_version: Mapped[str | None] = mapped_column(String(100))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` in the
    # migration -- read-only from the ORM's side (never assigned to; a
    # `Chunk` with no value set here is simply omitted from `INSERT`,
    # letting Postgres compute it). `deferred=True` so an ordinary
    # `SELECT` of a `Chunk` doesn't pull the tsvector payload along for
    # free; `PgVectorHybridRetrievalService` (`modules/retrieval/pgvector.py`)
    # is the one place that queries against it directly.
    content_tsv: Mapped[str | None] = mapped_column(TSVECTOR, deferred=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
