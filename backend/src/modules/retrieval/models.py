"""ORM models for the documents/chunks tables. Owned by retrieval (required at every chat turn), not ingestion (batch-only) -- ingestion imports from here, not the reverse."""

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

# Must match Settings.EMBEDDING_DIMENSION and the initial migration's own constant -- a width change needs a migration, not just an .env edit.
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
    # Dedupe key for reranked results sharing a source section; null when a chunk has no parent.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSION))
    embedding_version: Mapped[str | None] = mapped_column(String(100))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Generated column (to_tsvector), computed by Postgres -- never assigned from the ORM. deferred=True keeps ordinary SELECTs from pulling it.
    content_tsv: Mapped[str | None] = mapped_column(TSVECTOR, deferred=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
