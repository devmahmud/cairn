"""Current-user resolution -- real JWT auth, fixed identity for eval/CI (BLUEPRINT.md §3.9, §8 step 7).

Every ownership-scoped router (`conversations`, `chat`) depends on
`get_current_user_id`, never on `fastapi-users` directly -- that seam is
what made this file's previous revision (a caller-supplied `X-User-Id`
header, refused outside `ENVIRONMENT=local`) a one-file swap to real auth:
every router below is unchanged.

Verifies the access token independently with `PyJWT` against
`settings.JWT_SECRET`, rather than depending on
`modules.auth.users.current_active_user`. Two reasons, not just one:

1. **Layering.** `core/` must not import from `modules/` (§3.1: "deps flow
   one way: `agents/modules -> core`"; `core/di/container.py`'s own
   docstring calls itself "the one sanctioned place" that imports the
   other direction, and that's for the singleton *graph* specifically, not
   a second precedent to extend here).
2. **It's the same verification either way.** `modules/auth/users.py`'s
   `JWTStrategy` is itself a thin wrapper over `PyJWT`, signing
   `{"sub": <user id>, "aud": [TOKEN_AUDIENCE]}` -- `_TOKEN_AUDIENCE` below
   must stay in lockstep with `modules/auth/users.py::TOKEN_AUDIENCE` (both
   are the literal string `"fastapi-users:auth"`, `fastapi-users`' own
   default).

**Trade-off, stated plainly** (matching this template's existing stance,
§3.12: "the structlog censor is logs-only and is not data protection --
say so loudly"): this does **not** re-check `is_active`/deletion against
the database on every request the way `fastapi-users`' own
`current_active_user` dependency does (that costs a DB round trip per
request; `modules/auth/router.py`'s `/auth/me` uses that heavier
dependency precisely because it's a single "who am I" call, not every
ownership-scoped request in the app). A deactivated user's still-valid
access token keeps working until it naturally expires
(`ACCESS_TOKEN_LIFETIME_SECONDS`, one hour by default) -- bounded, and the
revocable refresh-token layer (`modules/auth/refresh_tokens.py`) means a
deactivated/logged-out user can't mint a *new* access token past that
window. A deployment that needs tighter revocation than "one access-token
lifetime" should shorten `ACCESS_TOKEN_LIFETIME_SECONDS` or add a DB check
here -- this file is small and self-contained specifically so that's a
local, obvious change.

**`AUTH_ENABLED` branch, decided once at import time, not per call**
(`AUTH_ENABLED` is tier-1 static config, §3.2: boot-time, immutable for the
process's life -- the same posture `agents/config.py`'s `_ROLE_CONFIGS`
already takes on other `Settings` values):

- `AUTH_ENABLED=true` (default, §3.9: "on by default, not a demo") --
  `get_current_user_id` requires a valid `Authorization: Bearer <jwt>`
  header; 401 on anything missing/malformed/invalid/expired.
- `AUTH_ENABLED=false` (eval/CI only, §3.2: "remains available for eval/CI
  runs that don't need identity") -- `get_current_user_id` takes no
  dependencies and always returns `ANONYMOUS_USER_ID`, a fixed, well-known
  UUID seeded by migration `b4b2a5d7c8e1_auth_refresh_tokens_and_anon_user`
  so the FK from `conversations.user_id` never dangles. Every request in
  this mode shares one identity -- correct for a single-tenant eval
  harness, not a real deployment, which is exactly why `AUTH_ENABLED=true`
  is the reference default, not this.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Header

from core.config import settings
from core.errors.exceptions import UnauthorizedError

#: Must match `modules/auth/users.py::TOKEN_AUDIENCE` -- `fastapi-users`'
#: default JWT-strategy audience claim.
_TOKEN_AUDIENCE = "fastapi-users:auth"

#: Fixed, well-known identity for `AUTH_ENABLED=false` (eval/CI, §3.2).
ANONYMOUS_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


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
    # Deliberately a different signature than the `AUTH_ENABLED=true` branch
    # above (no `authorization` parameter at all -- this mode never reads
    # the header) -- `type: ignore[misc]` silences mypy's "all conditional
    # function variants must have identical signatures" check, which is
    # about accidental redefinition, not this file's *intentional* one
    # (module docstring: "decided once here at import time").
    async def get_current_user_id() -> UUID:  # type: ignore[misc]
        return ANONYMOUS_USER_ID
