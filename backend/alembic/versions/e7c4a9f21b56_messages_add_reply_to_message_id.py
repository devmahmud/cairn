"""messages: add reply_to_message_id (assistant -> user message link)

Revision ID: e7c4a9f21b56
Revises: b4b2a5d7c8e1
Create Date: 2026-08-17 20:15:00.000000

Closes a correctness gap in the `/chat` idempotency-retry path (BLUEPRINT.md
§3.3): `ChatStreamer._existing_reply` used to locate a retried turn's
already-persisted assistant reply by grabbing "the most recent message in
the whole conversation" -- unsound once the conversation has moved on to a
later turn by the time a stale retry arrives, and useless while the
*original* attempt is still generating (no assistant row exists yet, so a
concurrent retry fell through to re-running the whole graph a second time).

This column gives the assistant reply an explicit FK back to the specific
user message it answers, so a retry can look up *its own* turn's reply
directly instead of guessing from recency.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c4a9f21b56"
down_revision: str | Sequence[str] | None = "b4b2a5d7c8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "reply_to_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Unique, not just indexed: a user message has at most one reply
    # (`ChatStreamer._persist_reply` sets this exactly once, at the end of
    # exactly one turn) -- the constraint makes that an enforced invariant,
    # not just a convention, and doubles as the index the retry-lookup query
    # (`MessageRepository.get_reply_to`) needs.
    op.create_index(
        "uq_messages_reply_to_message_id",
        "messages",
        ["reply_to_message_id"],
        unique=True,
        postgresql_where=sa.text("reply_to_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_messages_reply_to_message_id", table_name="messages")
    op.drop_column("messages", "reply_to_message_id")
