"""ORM models for the auth module (BLUEPRINT.md §3.3, §3.9, §8 step 7).

`User` is the real replacement for `modules/conversations/models.py`'s
interim `_users_table` stand-in -- it maps the *same* `users` table the
initial migration already created (columns chosen there specifically to
match `fastapi-users`' expectations: `hashed_password`/`is_active`/
`is_verified`/`is_superuser`, per that migration's own docstring), so no
migration is needed just to grow the table. `SQLAlchemyBaseUserTableUUID`
supplies `id`/`email`/`hashed_password`/`is_active`/`is_superuser`/
`is_verified`; `profile`/`created_at`/`updated_at` are added on top to match
the migration's remaining columns.

`RefreshToken` backs `modules/auth/refresh_tokens.py`'s rotation/revocation
-- see that module's docstring for why this template pairs a short-lived
JWT access token with a DB-backed, revocable refresh token rather than
relying on `fastapi-users`' stock JWT backend alone (which has no built-in
refresh/revocation story for a stateless token).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 hex digest of the raw token -- the raw value is only ever
    # returned to the client once, at issuance/rotation time, never stored
    # (`modules/auth/refresh_tokens.py::_hash`).
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
