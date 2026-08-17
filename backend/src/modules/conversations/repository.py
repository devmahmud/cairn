"""Explicit, typed repositories for conversations/messages (BLUEPRINT.md §3.3).

No generic `field__op` filter DSL (§3.3) -- every query method here is a
concrete, typed `select()` a caller (and mypy) can reason about directly.
Ownership is enforced here, not just in the router/service layer above it
(§3.9: "ownership checks enforced on every conversations/messages query --
`user_id` scoping at the repository layer, not just the router").
"""

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

    async def create_idempotent(self, message: Message) -> tuple[Message, bool]:
        """Insert a message, honoring the idempotency partial-unique index
        (`uq_messages_conversation_idempotency_key`, §3.3).

        Returns `(message, created)`. `created=False` means a message with
        the same `(conversation_id, idempotency_key)` already existed and
        *that* row is returned untouched -- a retry/reconnect is a no-op,
        never a double-write (§3.3's idempotency rule). A `None`
        `idempotency_key` always inserts (there is nothing to dedupe
        against -- the partial index only covers non-null keys).
        """
        if message.idempotency_key is None:
            return await self.add(message), True

        # Bare `on_conflict_do_nothing()` (no conflict target) triggers on
        # *any* unique/exclusion violation, including a partial unique
        # index -- unlike a targeted conflict clause, it needs no `WHERE`
        # predicate restated to match the migration's partial index.
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
