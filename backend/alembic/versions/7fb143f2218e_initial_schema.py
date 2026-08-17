"""initial schema

Revision ID: 7fb143f2218e
Revises:
Create Date: 2026-08-17 18:42:43.442733

Creates the neutral core schema (BLUEPRINT.md §2, §3.3): the `vector`
extension, `users` / `conversations` / `messages` / `documents` / `chunks`
(hybrid-search-ready: HNSW + a generated `tsvector` + GIN), the
`config_overrides` runtime-control table, and an optional `events` audit
log.

Deliberately NOT created here: LangGraph's checkpoint tables. Those are
owned by `AsyncPostgresSaver.setup()`, run once at app startup (§3.3) --
Alembic must never race it or try to duplicate its own migrations.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "7fb143f2218e"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match `core.config.Settings.EMBEDDING_DIMENSION`. Hardcoded (not
# imported from Settings) so this migration stays a faithful, reproducible
# record of what actually ran -- a later `.env` change doesn't retroactively
# alter history; it needs its own migration.
EMBEDDING_DIMENSION = 1024


def upgrade() -> None:
    # --- pgvector extension, floor-checked -----------------------------
    # 0.8.0/0.8.1 have a parallel-HNSW-build CVE; require >=0.8.2 (§3.3).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute(
        """
        DO $$
        DECLARE
            v_version text;
        BEGIN
            SELECT extversion INTO v_version FROM pg_extension WHERE extname = 'vector';
            IF v_version IS NULL THEN
                RAISE EXCEPTION 'pgvector extension is not installed';
            ELSIF string_to_array(v_version, '.')::int[] < string_to_array('0.8.2', '.')::int[] THEN
                RAISE EXCEPTION
                    'pgvector % is below the 0.8.2 floor required by BLUEPRINT.md §3.3 '
                    '(0.8.0/0.8.1 have a parallel-HNSW-build CVE) -- upgrade the extension first',
                    v_version;
            END IF;
        END
        $$;
        """
    )

    # --- users -----------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "profile", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("uq_users_email", "users", ["email"], unique=True)

    # --- conversations -----------------------------------------------------
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_embedding", Vector(EMBEDDING_DIMENSION), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    # --- messages -- the queryable history of record (§3.3) -----------------
    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "artifacts", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "citations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        # Nullable, deduped via the partial unique index below rather than a
        # plain NOT NULL/unique column -- most messages (assistant replies,
        # tool turns) never carry a client idempotency key at all. The ones
        # that do (`/chat` retries/reconnects, §3.3) get `INSERT ... ON
        # CONFLICT (conversation_id, idempotency_key) DO NOTHING` for free.
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index(
        "uq_messages_conversation_idempotency_key",
        "messages",
        ["conversation_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # --- documents / chunks -- RAG corpus (§3.3, §3.8) -----------------------
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Dedupe key for reranked results sharing a source section (§3.8:
        # "dedupe by parent_id"); null for a chunk that has no parent.
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=True),
        sa.Column("embedding_version", sa.String(100), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_parent_id", "chunks", ["parent_id"])

    # Hybrid retrieval (§3.3's SQL snippet, verbatim): a generated,
    # always-in-sync tsvector column -- a BM25 *approximation* only (no IDF/
    # doc-length normalization; swap in pg_search/pg_textsearch for real
    # BM25 if lexical ranking quality matters) -- plus its GIN index, and
    # the HNSW vector index (m=16, ef_construction=64).
    op.execute(
        "ALTER TABLE chunks ADD COLUMN content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;"
    )
    op.execute("CREATE INDEX ix_chunks_content_tsv ON chunks USING gin (content_tsv);")
    # Building the HNSW index on a large corpus needs `maintenance_work_mem`
    # raised (4-16GB per §3.3) or it falls to a 10-50x slower disk-based
    # build path. Irrelevant for the tiny bundled sample_corpus, so not set
    # here -- raise it in your session/role before `make ingest` at scale.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
    )

    # --- config_overrides -- runtime control plane (§3.2) ---------------------
    op.create_table(
        "config_overrides",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- events -- optional append-only audit/analytics projection (§3.3) -----
    # NOT the execution-state backbone -- that's the LangGraph checkpointer.
    # This is for auditing tool calls / state transitions after the fact.
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_events_conversation_id", "events", ["conversation_id"])
    op.create_index("ix_events_created_at", "events", ["created_at"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("config_overrides")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector;")
