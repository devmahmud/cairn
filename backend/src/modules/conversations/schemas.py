"""Pydantic request/response schemas for the conversations module (BLUEPRINT.md §3.3).

Plain `response_model`s, no global envelope (§3.9) -- OpenAPI stays
truthful, which is what full typed-client codegen (§4.3) needs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ConversationStatus = Literal["active", "archived"]
MessageRole = Literal["user", "assistant", "system", "tool"]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    status: ConversationStatus | None = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str | None
    status: str
    summary: str | None
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    items: list[ConversationRead]
    next_cursor: str | None = None


class MessageCreate(BaseModel):
    role: MessageRole
    content: str = Field(min_length=1)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=255)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    artifacts: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageRead]
    next_cursor: str | None = None
