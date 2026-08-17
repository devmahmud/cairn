"""Pydantic schemas for the auth module (BLUEPRINT.md §3.9, §8 step 7).

`UserRead`/`UserCreate`/`UserUpdate` are `fastapi-users`' own generic
schemas, narrowed to a UUID id -- no fields added here (`profile` is an
internal, not-yet-API-surfaced column; expose it explicitly later if a
client needs to read/write it). `TokenPair`/`RefreshRequest` are this
template's own -- `fastapi-users` has no opinion on refresh-token shape
since it doesn't implement refresh itself (`modules/auth/refresh_tokens.py`'s
docstring explains why this template adds one).
"""

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
