"""Request schema for the chat streaming endpoint (BLUEPRINT.md §3.7, §8 step 6).

Deliberately not `modules/conversations/schemas.py::MessageCreate` -- a chat
turn's input is "the text plus an existing conversation to run it in", not a
generic message row (no `role`/`artifacts`/`citations` to accept from a
client, and `content` here is renamed `text` to read naturally against
`ChatStreamer`'s own signature).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ChatTurnRequest(BaseModel):
    conversation_id: UUID
    text: str = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=255)
