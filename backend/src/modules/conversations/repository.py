"""Ownership (user_id scoping) is enforced here at the repository layer, not just in the router/service layer above it."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.repository.base import BaseRepository, Page
from modules.conversations.models import Conversation, Message


class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Conversation)

    async def get_owned(self, conversation_id: UUID, *, user_id: UUID) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        after: tuple[datetime, UUID] | None = None,
        limit: int | None = None,
    ) -> Page[Conversation]:
        stmt = select(Conversation).where(Conversation.user_id == user_id)
        return await self._paginate_keyset(
            stmt,
            order_by=Conversation.created_at,
            tiebreaker=Conversation.id,
            after=after,
            limit=limit,
        )


class MessageRepository(BaseRepository[Message]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Message)

    async def get_owned(
        self, message_id: UUID, *, conversation_id: UUID, user_id: UUID
    ) -> Message | None:
        stmt = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_conversation(
        self,
        conversation_id: UUID,
        *,
        after: tuple[datetime, UUID] | None = None,
        limit: int | None = None,
    ) -> Page[Message]:
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        return await self._paginate_keyset(
            stmt,
            order_by=Message.created_at,
            tiebreaker=Message.id,
            after=after,
            limit=limit,
        )

    async def get_reply_to(self, user_message_id: UUID) -> Message | None:
        """Replaces the old, unsound "most recent message in conversation" heuristic for finding a retried turn's own reply."""
        stmt = select(Message).where(Message.reply_to_message_id == user_message_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_idempotent(self, message: Message) -> tuple[Message, bool]:
        """(message, created) -- created=False means a same-key message already existed and was returned untouched, not double-written. A None key always inserts."""
        if message.idempotency_key is None:
            return await self.add(message), True

        # Bare on_conflict_do_nothing() (no conflict target) matches any unique violation, including this partial index, without restating its WHERE predicate.
        stmt = (
            pg_insert(Message)
            .values(
                conversation_id=message.conversation_id,
                role=message.role,
                content=message.content,
                artifacts=message.artifacts,
                citations=message.citations,
                idempotency_key=message.idempotency_key,
            )
            .on_conflict_do_nothing()
            .returning(Message)
        )
        inserted = (await self.session.execute(stmt)).scalar_one_or_none()
        if inserted is not None:
            return inserted, True

        existing_stmt = select(Message).where(
            Message.conversation_id == message.conversation_id,
            Message.idempotency_key == message.idempotency_key,
        )
        existing = (await self.session.execute(existing_stmt)).scalar_one()
        return existing, False
