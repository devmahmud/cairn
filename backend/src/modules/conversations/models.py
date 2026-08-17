"""ORM models for the conversations vertical slice (BLUEPRINT.md §3.3).

Maps onto the `conversations` / `messages` tables the initial migration
already created (`alembic/versions/7fb143f2218e_initial_schema.py`) -- this
file does not create or alter schema. `users` is referenced by FK but
deliberately not mapped as a full ORM class here: the `users` table belongs
to the not-yet-built auth module (§8 step 7), and mapping it fully here
would put a domain model outside the module that owns it. It still needs
*some* `Table` registered under that name in `Base.metadata`, though --
SQLAlchemy's unit-of-work resolves every FK's target table at flush/
insert-ordering time, not just at DDL-generation time, so a bare
`ForeignKey("users.id")` string with no matching table in the same
metadata raises `NoReferencedTableError` the moment a `Conversation` is
ever inserted. `_users_table` below is that minimal stand-in -- see its
docstring for how step 7 should reconcile it with the real `User` model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base

# Must match `core.config.Settings.EMBEDDING_DIMENSION` *and* the initial
# migration's own `EMBEDDING_DIMENSION` constant -- hardcoded here for the
# same reason the migration hardcodes it: changing the actual column width
# needs a new migration, not just an `.env` edit (BLUEPRINT.md §3.3).
EMBEDDING_DIMENSION = 1024

# Core-only (not ORM-mapped) stand-in for the `users` table so
# `Conversation.user_id`'s FK below has something to resolve against. §8
# step 7's `User` ORM model should either point `__table__` at this same
# `Table` object (`Base.metadata.tables["users"]`) or otherwise ensure only
# one definition of "users" is registered in `Base.metadata` -- two
# competing `Table("users", ...)` calls without `extend_existing=True`
# raise on import.
_users_table = Table(
    "users",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="active")
    summary: Mapped[str | None] = mapped_column(Text())
    summary_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSION))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Nullable; deduped via the migration's partial unique index
    # (`conversation_id`, `idempotency_key`) `WHERE idempotency_key IS NOT
    # NULL` -- see `repository.py::MessageRepository.create_idempotent`.
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
