"""fastapi-users' JWT backend is stateless with no refresh/revoke -- this pairs it with a DB-backed refresh-token table: hashed at rest, single-use (rotated), revocable on logout."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.errors.exceptions import UnauthorizedError
from modules.auth.models import RefreshToken

_TOKEN_BYTES = 32


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def issue(self, user_id: UUID) -> tuple[str, datetime]:
        """Returns the raw token value, given to the client exactly once, and its expiry."""
        raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.REFRESH_TOKEN_LIFETIME_SECONDS)
        self.session.add(
            RefreshToken(user_id=user_id, token_hash=_hash(raw_token), expires_at=expires_at)
        )
        await self.session.flush()
        return raw_token, expires_at

    async def rotate(self, raw_token: str) -> UUID:
        """Revokes raw_token and returns its user_id; the caller mints the replacement via a separate issue() call, so logout doesn't need an issuing variant."""
        row = await self._get_active(raw_token)
        row.revoked_at = datetime.now(UTC)
        await self.session.flush()
        return row.user_id

    async def revoke(self, raw_token: str) -> None:
        """Unlike rotate, revoking an already-invalid token is a silent no-op -- logout shouldn't fail just because the token was already gone."""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == _hash(raw_token))
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await self.session.flush()

    async def _get_active(self, raw_token: str) -> RefreshToken:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == _hash(raw_token))
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None or row.revoked_at is not None or row.expires_at < now:
            raise UnauthorizedError("Invalid, expired, or already-used refresh token.")
        return row
