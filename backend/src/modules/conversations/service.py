"""Ownership-boundary errors ("doesn't exist" and "not yours") both map to the same NotFoundError -- a caller must never distinguish the two from the response."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from core.errors.exceptions import NotFoundError
from modules.conversations import pagination
from modules.conversations.models import Conversation, Message
from modules.conversations.repository import ConversationRepository, MessageRepository
from modules.conversations.schemas import (
    ConversationCreate,
    ConversationPage,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessagePage,
    MessageRead,
)


class ConversationService:
    def __init__(
        self,
        conversations: ConversationRepository,
        messages: MessageRepository,
    ) -> None:
        self._conversations = conversations
        self._messages = messages

    async def create_conversation(
        self, *, user_id: uuid.UUID, payload: ConversationCreate
    ) -> ConversationRead:
        conversation = Conversation(user_id=user_id, title=payload.title)
        conversation = await self._conversations.add(conversation)
        return ConversationRead.model_validate(conversation)

    async def get_conversation(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> ConversationRead:
        conversation = await self._get_owned_or_404(conversation_id, user_id=user_id)
        return ConversationRead.model_validate(conversation)

    async def list_conversations(
        self, *, user_id: uuid.UUID, cursor: str | None, limit: int | None
    ) -> ConversationPage:
        after = pagination.decode_cursor(cursor) if cursor else None
        page = await self._conversations.list_for_user(user_id, after=after, limit=limit)
        next_cursor = pagination.encode_cursor(*page.next_cursor) if page.next_cursor else None
        return ConversationPage(
            items=[ConversationRead.model_validate(c) for c in page.items],
            next_cursor=next_cursor,
        )

    async def update_conversation(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID, payload: ConversationUpdate
    ) -> ConversationRead:
        conversation = await self._get_owned_or_404(conversation_id, user_id=user_id)
        if payload.title is not None:
            conversation.title = payload.title
        if payload.status is not None:
            conversation.status = payload.status
        conversation.updated_at = datetime.now(UTC)
        conversation = await self._conversations.add(conversation)
        return ConversationRead.model_validate(conversation)

    async def delete_conversation(self, conversation_id: uuid.UUID, *, user_id: uuid.UUID) -> None:
        conversation = await self._get_owned_or_404(conversation_id, user_id=user_id)
        await self._conversations.delete(conversation)

    async def add_message(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID, payload: MessageCreate
    ) -> MessageRead:
        await self._get_owned_or_404(conversation_id, user_id=user_id)

        message = Message(
            conversation_id=conversation_id,
            role=payload.role,
            content=payload.content,
            artifacts=payload.artifacts,
            citations=payload.citations,
            idempotency_key=payload.idempotency_key,
        )
        message, _created = await self._messages.create_idempotent(message)
        return MessageRead.model_validate(message)

    async def list_messages(
        self,
        conversation_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        cursor: str | None,
        limit: int | None,
    ) -> MessagePage:
        await self._get_owned_or_404(conversation_id, user_id=user_id)

        after = pagination.decode_cursor(cursor) if cursor else None
        page = await self._messages.list_for_conversation(conversation_id, after=after, limit=limit)
        next_cursor = pagination.encode_cursor(*page.next_cursor) if page.next_cursor else None
        return MessagePage(
            items=[MessageRead.model_validate(m) for m in page.items],
            next_cursor=next_cursor,
        )

    async def _get_owned_or_404(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> Conversation:
        conversation = await self._conversations.get_owned(conversation_id, user_id=user_id)
        if conversation is None:
            raise NotFoundError(f"Conversation {conversation_id} not found.")
        return conversation
