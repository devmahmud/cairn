"""login/refresh/logout are hand-rolled instead of fastapi-users' bundled router -- see refresh_tokens.py for why."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.engine import get_session
from core.errors.exceptions import UnauthorizedError
from modules.auth.models import User
from modules.auth.refresh_tokens import RefreshTokenRepository
from modules.auth.schemas import RefreshRequest, TokenPair, UserCreate, UserRead
from modules.auth.users import (
    UserManager,
    current_active_user,
    fastapi_users,
    get_jwt_strategy,
    get_user_manager,
)

router = APIRouter(prefix="/auth", tags=["auth"])

router.include_router(fastapi_users.get_register_router(UserRead, UserCreate))

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserManagerDep = Annotated[UserManager, Depends(get_user_manager)]


async def _issue_pair(user: User, session: AsyncSession) -> TokenPair:
    access_token = await get_jwt_strategy().write_token(user)
    refresh_token, _expires_at = await RefreshTokenRepository(session).issue(user.id)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenPair)
async def login(
    credentials: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_manager: UserManagerDep,
    session: SessionDep,
) -> TokenPair:
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        raise UnauthorizedError("Incorrect email or password.")
    return await _issue_pair(user, session)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    user_manager: UserManagerDep,
    session: SessionDep,
) -> TokenPair:
    user_id = await RefreshTokenRepository(session).rotate(payload.refresh_token)
    user = await user_manager.get(user_id)
    if not user.is_active:
        raise UnauthorizedError("This account is no longer active.")
    return await _issue_pair(user, session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, session: SessionDep) -> None:
    await RefreshTokenRepository(session).revoke(payload.refresh_token)


@router.get("/me", response_model=UserRead)
async def me(user: Annotated[User, Depends(current_active_user)]) -> User:
    return user
