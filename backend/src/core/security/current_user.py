"""Interim current-user resolution (BLUEPRINT.md §3.9, §8 step 7).

`fastapi-users` (JWT-backed, refresh rotation, revocation) is the real
identity provider and lands in a later scaffold step (§3.9, §8 step 7).
Every ownership-scoped router depends on `get_current_user_id`, not a
header directly, so wiring real auth later is a one-file change: swap this
function's body for `fastapi-users`' `current_active_user` dependency and
every caller keeps working unmodified.

Until then, this trusts a caller-supplied `X-User-Id` header. That is
**not authentication** -- a header is trivially spoofable -- so it is
refused outside `ENVIRONMENT=local` (the same whitelist `core/config.py`'s
`JWT_SECRET` fail-fast uses); it exists only so the `conversations`
module's ownership scoping (§3.9: "user_id scoping at the repository
layer") is exercised by a real request flow today, ahead of step 7 wiring
real JWT verification.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Header

from core.config import settings
from core.errors.exceptions import ServiceUnavailableError, UnauthorizedError


def get_current_user_id(
    x_user_id: Annotated[UUID | None, Header(alias="X-User-Id")] = None,
) -> UUID:
    if settings.ENVIRONMENT != "local":
        raise ServiceUnavailableError(
            "Real authentication (fastapi-users, BLUEPRINT.md §8 step 7) is not "
            "wired yet; refusing to trust a caller-supplied identity header "
            f"outside local dev (ENVIRONMENT={settings.ENVIRONMENT!r})."
        )
    if x_user_id is None:
        raise UnauthorizedError("Missing X-User-Id header.")
    return x_user_id
