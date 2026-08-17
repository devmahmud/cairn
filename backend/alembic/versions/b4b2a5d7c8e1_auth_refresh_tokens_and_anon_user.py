"""auth: refresh_tokens table + seeded anonymous user

Revision ID: b4b2a5d7c8e1
Revises: 7fb143f2218e
Create Date: 2026-08-17 19:30:00.000000

Two additions for real auth (BLUEPRINT.md §3.9, §8 step 7). The `users`
table itself needs no migration here -- the initial migration already
created it with exactly the columns `fastapi-users`' `SQLAlchemyBaseUserTableUUID`
expects (`hashed_password`/`is_active`/`is_verified`/`is_superuser`,
matching `modules/auth/models.py::User`).

1. **`refresh_tokens`** -- backs `modules/auth/refresh_tokens.py`'s DB-
   backed refresh-token rotation/revocation (stock `fastapi-users` JWT auth
   has no refresh/revocation story on its own; see that module's
   docstring).
2. **A seeded anonymous user row** -- `core/security/current_user.py`'s
   `ANONYMOUS_USER_ID`, the fixed identity `AUTH_ENABLED=false` (eval/CI)
   mode returns for every request. Without this row, `conversations.user_id`'s
   `NOT NULL` FK to `users.id` would reject every write in that mode; with
   it, `AUTH_ENABLED=false` boots and runs with no further setup, matching
   this step's brief ("the app should still boot and run" in that mode).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4b2a5d7c8e1"
down_revision: str | Sequence[str] | None = "7fb143f2218e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `core.security.current_user.ANONYMOUS_USER_ID` -- kept as a literal here
#: too (not imported), the same "a migration is a reproducible record of
#: what actually ran" stance the initial migration's own
#: `EMBEDDING_DIMENSION` constant documents.
_ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
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
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("uq_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    op.execute(
        sa.text(
            "INSERT INTO users (id, email, hashed_password, is_active, is_verified, is_superuser) "
            "VALUES (:id, 'anonymous@local.invalid', '', true, true, false) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(sa.bindparam("id", value=_ANONYMOUS_USER_ID, type_=postgresql.UUID(as_uuid=False)))
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM users WHERE id = :id").bindparams(
            sa.bindparam("id", value=_ANONYMOUS_USER_ID, type_=postgresql.UUID(as_uuid=False))
        )
    )
    op.drop_table("refresh_tokens")
