"""ORM models for the conversations vertical slice (BLUEPRINT.md §3.3).

Maps onto the `conversations` / `messages` tables the initial migration
already created (`alembic/versions/7fb143f2218e_initial_schema.py`) -- this
file does not create or alter schema. `users` is referenced by FK
(`Conversation.user_id`) but deliberately not mapped as a full ORM class
here: the real `User` model belongs to `modules/auth/models.py`, the module
that owns that table (§8 step 7).

Nothing here imports `modules.auth.models` to make that FK resolvable --
it doesn't need to. SQLAlchemy resolves a string `ForeignKey`'s target
table lazily, at flush/mapper-configuration time, not at class-definition
time (its own unit-of-work needs to know insert/dependency ordering
between tables, which is when it actually looks `"users"` up in
`Base.metadata.tables`) -- so as long as `modules.auth.models` has been
imported *somewhere* in the process before the first real flush (true for
every real request: `routers.py` mounts both `conversations` and `auth`),
the FK resolves correctly regardless of which module happened to import
first. `tests/unit/test_conversations_service.py` (the one place outside
the app itself that imports this module) never flushes a real `Conversation`
row at all -- fake repositories, no session -- so it never exercises this
path either way.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base

# Must match `core.config.Settings.EMBEDDING_DIMENSION` *and* the initial
# migration's own `EMBEDDING_DIMENSION` constant -- hardcoded here for the
# same reason the migration hardcodes it: changing the actual column width
# needs a new migration, not just an `.env` edit (BLUEPRINT.md §3.3).
EMBEDDING_DIMENSION = 1024


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
    # Self-referential: set only on an assistant reply, pointing at the
    # specific user `Message` it answers (`modules/chat/chat_stream.py`'s
    # `ChatStreamer._persist_reply`). A partial unique index (migration
    # `e7c4a9f21b56`) enforces "at most one reply per user message" and
    # doubles as the lookup index `MessageRepository.get_reply_to` needs to
    # replay a retried turn's *own* reply instead of guessing from
    # conversation recency (§3.3).
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
