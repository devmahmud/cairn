"""DB-backed refresh-token rotation + revocation (BLUEPRINT.md §3.9, §8 step 7).

`fastapi-users`' stock JWT backend is stateless and short-lived by design --
there's no built-in "refresh" concept (a new access token normally just
means logging in again) and its `/logout` route is a no-op for a JWT
strategy (nothing server-side to invalidate). That's a real gap against
this step's brief ("register/login/refresh/logout endpoints" with genuine
revocation), so this template pairs `fastapi-users`' JWT access tokens with
its own minimal, DB-backed refresh-token table:

- **Issue** a random, high-entropy token at login; store only its SHA-256
  hash (never the raw value -- the same posture a password hash gets).
- **Rotate** on every `/auth/refresh` call: the presented token is revoked
  and a new one issued in the same operation, so a refresh token is
  single-use (limits the blast radius of a leaked one to one exchange).
- **Revoke** on `/auth/logout` -- immediate, real invalidation (unlike the
  JWT access token itself, which stays valid until its own short expiry;
  `core/security/current_user.py`'s docstring states that trade-off
  explicitly).

Callers own the session's transaction boundary (this class never calls
`session.commit()`), matching every other repository in this codebase
(`core/repository/base.py`'s docstring).
"""

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
        """Mint and store a new refresh token for `user_id`; return the raw
        value (returned to the client exactly once) and its expiry."""
        raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.REFRESH_TOKEN_LIFETIME_SECONDS)
        self.session.add(
            RefreshToken(user_id=user_id, token_hash=_hash(raw_token), expires_at=expires_at)
        )
        await self.session.flush()
        return raw_token, expires_at

    async def rotate(self, raw_token: str) -> UUID:
        """Revoke `raw_token` and return the `user_id` it belonged to.

        Raises `UnauthorizedError` if the token is unknown, already
        revoked, or expired -- the caller (`modules/auth/router.py`) mints
        the actual replacement via a fresh `issue()` call, kept as two
        explicit steps rather than one method so a caller that only wants
        to revoke (`/auth/logout`) doesn't need a variant that also issues.
        """
        row = await self._get_active(raw_token)
        row.revoked_at = datetime.now(UTC)
        await self.session.flush()
        return row.user_id

    async def revoke(self, raw_token: str) -> None:
        """Best-effort revoke -- unlike `rotate`, an already-invalid token
        is a silent no-op (logout should never fail because the token was
        already revoked/expired/unknown; the caller's intent -- "this
        token shouldn't work anymore" -- is already satisfied)."""
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
