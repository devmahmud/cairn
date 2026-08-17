"""`fastapi-users` wiring: user manager, DB adapter, JWT backend (BLUEPRINT.md §3.9, §8 step 7).

`get_session` (`core/db/engine.py`, commit-per-request) is reused as-is for
the user-manager's DB access -- FastAPI caches a `Depends(get_session)`
resolution per request, so `modules/auth/router.py` depending on
`get_session` directly *and* transitively through `get_user_manager` shares
the same session/transaction rather than opening two.

`current_active_user` is `fastapi-users`' own dependency (hits the DB on
every call to check `is_active`) -- used directly by auth-specific routes
in this module (`/auth/me`) that want the full `User`, not just an id.
`core/security/current_user.py::get_current_user_id` (what `conversations`/
`chat` actually depend on) deliberately does **not** go through this --
see that module's docstring for why (stateless verification, no `core/` ->
`modules/` import).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db.engine import get_session
from modules.auth.models import User

#: Must match `core/security/current_user.py`'s `_TOKEN_AUDIENCE` -- that
#: module verifies the same tokens this one signs, independently (it can't
#: import this module, §3.1: "core/ must not depend on modules/").
TOKEN_AUDIENCE = "fastapi-users:auth"


async def get_user_db(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, uuid.UUID]]:
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    # Password-reset/email-verification tokens aren't issued by any route
    # this template wires up today (no `/auth/forgot-password` router, §8
    # step 7's explicit scope is register/login/refresh/logout) -- these
    # secrets exist because `BaseUserManager` requires them unconditionally,
    # reusing `JWT_SECRET` rather than inventing an unused second secret.
    reset_password_token_secret = settings.JWT_SECRET
    verification_token_secret = settings.JWT_SECRET


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase[User, uuid.UUID], Depends(get_user_db)],
) -> AsyncGenerator[UserManager]:
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="auth/login")


def get_jwt_strategy() -> JWTStrategy[User, uuid.UUID]:
    return JWTStrategy(
        secret=settings.JWT_SECRET,
        lifetime_seconds=settings.ACCESS_TOKEN_LIFETIME_SECONDS,
        token_audience=[TOKEN_AUDIENCE],
    )


# Registered with `FastAPIUsers` below so its own bundled routers (just
# `get_register_router` here, §8 step 7's scope) know how to issue a token
# if asked -- login/refresh/logout are hand-rolled in `router.py` instead,
# for the token-*pair* (access + revocable refresh) shape plain
# `fastapi-users` doesn't produce on its own.
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
