"""Deliberately not conversations/schemas.py's MessageCreate -- a chat turn's input is text + an existing conversation, not a generic message row."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ChatTurnRequest(BaseModel):
    conversation_id: UUID
    text: str = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=255)
