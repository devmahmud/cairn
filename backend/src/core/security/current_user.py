"""Verifies the access token independently via PyJWT rather than depending on modules.auth.users -- core/ must not import modules/, and it's the same check either way."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Header

from core.config import settings
from core.errors.exceptions import UnauthorizedError

#: Must match modules/auth/users.py::TOKEN_AUDIENCE.
_TOKEN_AUDIENCE = "fastapi-users:auth"

#: Fixed, well-known identity for AUTH_ENABLED=false (eval/CI).
ANONYMOUS_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


# Stateless: doesn't recheck is_active per request -- a deactivated user's token works until ACCESS_TOKEN_LIFETIME_SECONDS expires.
def _decode_user_id(token: str) -> UUID:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=["HS256"], audience=_TOKEN_AUDIENCE
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired access token.") from exc

    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Access token is missing a subject claim.")
    try:
        return UUID(str(sub))
    except ValueError as exc:
        raise UnauthorizedError("Access token subject is not a valid user id.") from exc


if settings.AUTH_ENABLED:

    async def get_current_user_id(
        authorization: Annotated[str | None, Header()] = None,
    ) -> UUID:
        if authorization is None or not authorization.lower().startswith("bearer "):
            raise UnauthorizedError("Missing or malformed Authorization header.")
        return _decode_user_id(authorization[7:].strip())

else:
    # Silences mypy's "conditional function variants must have identical signatures" check -- intentional here, not a redefinition bug.
    async def get_current_user_id() -> UUID:  # type: ignore[misc]
        return ANONYMOUS_USER_ID
