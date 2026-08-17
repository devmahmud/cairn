"""Unit tests for `modules.conversations.service.ConversationService` (BLUEPRINT.md §3.3).

Uses hand-rolled fake repositories (subclasses that override every method
the service calls, never touching a real session) instead of a database --
fixture-backed, no network, per §3.11. Keyset-pagination *correctness* is
already covered by `tests/unit/test_base_repository.py`; these tests only
check the service's own responsibilities: ownership -> 404 mapping, cursor
encode/decode wiring, and idempotent-create pass-through.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from core.errors.exceptions import NotFoundError
from core.repository.base import Page
from modules.conversations import pagination
from modules.conversations.models import Conversation, Message
from modules.conversations.repository import ConversationRepository, MessageRepository
from modules.conversations.schemas import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
)
from modules.conversations.service import ConversationService


class _FakeConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Conversation] = {}
        self.list_calls: list[tuple[uuid.UUID, tuple[datetime, uuid.UUID] | None, int | None]] = []
        self.next_page: Page[Conversation] | None = None

    async def get_owned(
        self, conversation_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> Conversation | None:
        row = self.rows.get(conversation_id)
        return row if row is not None and row.user_id == user_id else None

    async def add(self, instance: Conversation) -> Conversation:
        # Mimics the columns' `server_default`s a real flush against
        # Postgres would populate via implicit `INSERT ... RETURNING`
        # (BLUEPRINT.md's migration, `7fb143f2218e_initial_schema.py`).
        if instance.id is None:
            instance.id = uuid.uuid4()
        if instance.status is None:
            instance.status = "active"
        now = datetime.now(UTC)
        if instance.created_at is None:
            instance.created_at = now
        instance.updated_at = now
        self.rows[instance.id] = instance
        return instance

    async def delete(self, instance: Conversation) -> None:
        self.rows.pop(instance.id, None)

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        after: tuple[datetime, uuid.UUID] | None = None,
        limit: int | None = None,
    ) -> Page[Conversation]:
        self.list_calls.append((user_id, after, limit))
        assert self.next_page is not None, "test must set fake.next_page before calling"
        return self.next_page


class _FakeMessageRepository(MessageRepository):
    def __init__(self) -> None:
        self.create_idempotent_calls: list[Message] = []
        self.next_create_result: tuple[Message, bool] | None = None
        self.list_calls: list[tuple[uuid.UUID, tuple[datetime, uuid.UUID] | None, int | None]] = []
        self.next_page: Page[Message] | None = None

    async def create_idempotent(self, message: Message) -> tuple[Message, bool]:
        self.create_idempotent_calls.append(message)
        assert self.next_create_result is not None, "test must set fake.next_create_result"
        return self.next_create_result

    async def list_for_conversation(
        self,
        conversation_id: uuid.UUID,
        *,
        after: tuple[datetime, uuid.UUID] | None = None,
        limit: int | None = None,
    ) -> Page[Message]:
        self.list_calls.append((conversation_id, after, limit))
        assert self.next_page is not None, "test must set fake.next_page before calling"
        return self.next_page


@pytest.fixture
def conversations() -> _FakeConversationRepository:
    return _FakeConversationRepository()


@pytest.fixture
def messages() -> _FakeMessageRepository:
    return _FakeMessageRepository()


@pytest.fixture
def service(
    conversations: _FakeConversationRepository, messages: _FakeMessageRepository
) -> ConversationService:
    return ConversationService(conversations, messages)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_conversation(
    *,
    user_id: uuid.UUID,
    title: str | None = "Existing",
    status: str = "active",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(
        id=uuid.uuid4(),
        user_id=user_id,
        title=title,
        status=status,
        summary=None,
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


async def test_create_conversation_returns_read_model(
    service: ConversationService, user_id: uuid.UUID
) -> None:
    result = await service.create_conversation(
        user_id=user_id, payload=ConversationCreate(title="New chat")
    )

    assert result.user_id == user_id
    assert result.title == "New chat"
    assert result.status == "active"


async def test_get_conversation_not_found_raises(
    service: ConversationService, user_id: uuid.UUID
) -> None:
    with pytest.raises(NotFoundError):
        await service.get_conversation(uuid.uuid4(), user_id=user_id)


async def test_get_conversation_owned_by_someone_else_raises_not_found(
    service: ConversationService,
    conversations: _FakeConversationRepository,
    user_id: uuid.UUID,
) -> None:
    other_users_conversation = _make_conversation(user_id=uuid.uuid4())
    conversations.rows[other_users_conversation.id] = other_users_conversation

    with pytest.raises(NotFoundError):
        await service.get_conversation(other_users_conversation.id, user_id=user_id)


async def test_get_conversation_success(
    service: ConversationService,
    conversations: _FakeConversationRepository,
    user_id: uuid.UUID,
) -> None:
    conversation = _make_conversation(user_id=user_id, title="Mine")
    conversations.rows[conversation.id] = conversation

    result = await service.get_conversation(conversation.id, user_id=user_id)

    assert result.id == conversation.id
    assert result.title == "Mine"


async def test_update_conversation_applies_only_provided_fields(
    service: ConversationService,
    conversations: _FakeConversationRepository,
    user_id: uuid.UUID,
) -> None:
    stale_updated_at = datetime.now(UTC) - timedelta(days=1)
    conversation = _make_conversation(
        user_id=user_id, title="Original", status="active", updated_at=stale_updated_at
    )
    conversations.rows[conversation.id] = conversation

    result = await service.update_conversation(
        conversation.id,
        user_id=user_id,
        payload=ConversationUpdate(title=None, status="archived"),
    )

    assert result.title == "Original"  # untouched -- not provided in the payload
    assert result.status == "archived"
    assert result.updated_at > stale_updated_at


async def test_update_conversation_not_found_raises(
    service: ConversationService, user_id: uuid.UUID
) -> None:
    with pytest.raises(NotFoundError):
        await service.update_conversation(
            uuid.uuid4(), user_id=user_id, payload=ConversationUpdate(title="x")
        )


async def test_delete_conversation_removes_row(
    service: ConversationService,
    conversations: _FakeConversationRepository,
    user_id: uuid.UUID,
) -> None:
    conversation = _make_conversation(user_id=user_id)
    conversations.rows[conversation.id] = conversation

    await service.delete_conversation(conversation.id, user_id=user_id)

    assert conversation.id not in conversations.rows
    with pytest.raises(NotFoundError):
        await service.get_conversation(conversation.id, user_id=user_id)


async def test_list_conversations_decodes_cursor_and_encodes_next_cursor(
    service: ConversationService,
    conversations: _FakeConversationRepository,
    user_id: uuid.UUID,
) -> None:
    conversation = _make_conversation(user_id=user_id)
    next_created_at = datetime(2026, 1, 1, tzinfo=UTC)
    next_id = uuid.uuid4()
    conversations.next_page = Page(items=[conversation], next_cursor=(next_created_at, next_id))

    input_cursor_created_at = datetime(2025, 6, 1, tzinfo=UTC)
    input_cursor_id = uuid.uuid4()
    input_cursor = pagination.encode_cursor(input_cursor_created_at, input_cursor_id)

    result = await service.list_conversations(user_id=user_id, cursor=input_cursor, limit=25)

    # The service decoded our cursor and forwarded it as `after`.
    assert conversations.list_calls == [(user_id, (input_cursor_created_at, input_cursor_id), 25)]
    # And re-encoded the repository's returned cursor pair for the wire.
    assert result.next_cursor == pagination.encode_cursor(next_created_at, next_id)
    assert [c.id for c in result.items] == [conversation.id]


async def test_list_conversations_last_page_has_no_next_cursor(
    service: ConversationService,
    conversations: _FakeConversationRepository,
    user_id: uuid.UUID,
) -> None:
    conversations.next_page = Page(items=[], next_cursor=None)

    result = await service.list_conversations(user_id=user_id, cursor=None, limit=None)

    assert result.next_cursor is None
    assert conversations.list_calls == [(user_id, None, None)]


async def test_add_message_requires_owned_conversation(
    service: ConversationService, user_id: uuid.UUID
) -> None:
    with pytest.raises(NotFoundError):
        await service.add_message(
            uuid.uuid4(), user_id=user_id, payload=MessageCreate(role="user", content="hi")
        )


async def test_add_message_forwards_to_idempotent_create(
    service: ConversationService,
    conversations: _FakeConversationRepository,
    messages: _FakeMessageRepository,
    user_id: uuid.UUID,
) -> None:
    conversation = _make_conversation(user_id=user_id)
    conversations.rows[conversation.id] = conversation

    stored = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="user",
        content="hello",
        artifacts=[],
        citations=[],
        idempotency_key="key-1",
        created_at=datetime.now(UTC),
    )
    messages.next_create_result = (stored, True)

    result = await service.add_message(
        conversation.id,
        user_id=user_id,
        payload=MessageCreate(role="user", content="hello", idempotency_key="key-1"),
    )

    assert result.id == stored.id
    assert len(messages.create_idempotent_calls) == 1
    submitted = messages.create_idempotent_calls[0]
    assert submitted.conversation_id == conversation.id
    assert submitted.idempotency_key == "key-1"


async def test_list_messages_requires_owned_conversation(
    service: ConversationService, user_id: uuid.UUID
) -> None:
    with pytest.raises(NotFoundError):
        await service.list_messages(uuid.uuid4(), user_id=user_id, cursor=None, limit=None)


async def test_list_messages_decodes_cursor_and_encodes_next_cursor(
    service: ConversationService,
    conversations: _FakeConversationRepository,
    messages: _FakeMessageRepository,
    user_id: uuid.UUID,
) -> None:
    conversation = _make_conversation(user_id=user_id)
    conversations.rows[conversation.id] = conversation

    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="assistant",
        content="hi there",
        artifacts=[],
        citations=[],
        idempotency_key=None,
        created_at=datetime.now(UTC),
    )
    next_created_at = datetime(2026, 2, 2, tzinfo=UTC)
    next_id = uuid.uuid4()
    messages.next_page = Page(items=[message], next_cursor=(next_created_at, next_id))

    result = await service.list_messages(conversation.id, user_id=user_id, cursor=None, limit=10)

    assert messages.list_calls == [(conversation.id, None, 10)]
    assert result.next_cursor == pagination.encode_cursor(next_created_at, next_id)
    assert [m.id for m in result.items] == [message.id]
