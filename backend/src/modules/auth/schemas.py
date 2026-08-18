"""UserRead/UserCreate/UserUpdate are fastapi-users' own generic schemas; TokenPair/RefreshRequest are this template's own, since fastapi-users has no refresh concept."""

from __future__ import annotations

import uuid

from fastapi_users import schemas
from pydantic import BaseModel


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
