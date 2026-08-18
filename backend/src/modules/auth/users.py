"""fastapi-users wiring. get_current_user_id (core/security) is a separate stateless check -- core/ can't import this module."""

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

# Must match core/security/current_user.py's _TOKEN_AUDIENCE -- that module verifies these tokens independently and can't import this one.
TOKEN_AUDIENCE = "fastapi-users:auth"


async def get_user_db(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, uuid.UUID]]:
    # Depends(get_session) is cached per request by FastAPI, so this shares router's session/transaction rather than opening a second one.
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    # BaseUserManager requires these unconditionally though no reset/verify routes are wired up; reuse JWT_SECRET rather than add an unused one.
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


# Only get_register_router uses this backend -- login/refresh/logout are hand-rolled in router.py for the access+refresh token pair.
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
