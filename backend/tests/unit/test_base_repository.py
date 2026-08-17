"""Unit tests for `core.repository.base.BaseRepository` (BLUEPRINT.md §3.3).

Exercises the generic get/add/delete + keyset-pagination behavior against
an in-memory SQLite engine and a throwaway fixture model -- fixture-backed,
no network, per §3.11. Postgres-specific behavior of the `conversations`/
`messages` repositories (JSONB, pgvector, `ON CONFLICT`) is covered by the
integration test instead (`tests/integration/test_conversations_api.py`),
since those types don't exist on SQLite.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import DateTime, String, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from core.db.base import Base
from core.repository.base import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, BaseRepository


class _Widget(Base):
    """Throwaway fixture model -- exists only for this test module.

    Uses the dialect-portable `sqlalchemy.Uuid`/`DateTime`, not the
    Postgres-only types `modules/conversations/models.py` uses, so it can
    run against in-memory SQLite without a real Postgres.
    """

    __tablename__ = "test_base_repository_widgets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    widgets_table = Base.metadata.tables[_Widget.__tablename__]
    async with engine.begin() as conn:
        await conn.run_sync(widgets_table.create)

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as db_session:
        yield db_session

    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> BaseRepository[_Widget]:
    return BaseRepository(session, _Widget)


def _widget(name: str, *, created_at: datetime) -> _Widget:
    return _Widget(name=name, created_at=created_at)


async def test_add_persists_and_get_returns_it(repo: BaseRepository[_Widget]) -> None:
    widget = await repo.add(_widget("first", created_at=datetime.now(UTC)))

    fetched = await repo.get(widget.id)

    assert fetched is not None
    assert fetched.id == widget.id
    assert fetched.name == "first"


async def test_get_missing_returns_none(repo: BaseRepository[_Widget]) -> None:
    assert await repo.get(uuid.uuid4()) is None


async def test_delete_removes_row(repo: BaseRepository[_Widget]) -> None:
    widget = await repo.add(_widget("to-delete", created_at=datetime.now(UTC)))

    await repo.delete(widget)

    assert await repo.get(widget.id) is None


async def test_paginate_keyset_applies_default_limit(repo: BaseRepository[_Widget]) -> None:
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(DEFAULT_LIST_LIMIT + 5):
        await repo.add(_widget(f"w{i}", created_at=base_time + timedelta(milliseconds=i)))

    page = await repo._paginate_keyset(
        select(_Widget), order_by=_Widget.created_at, tiebreaker=_Widget.id
    )

    assert len(page.items) == DEFAULT_LIST_LIMIT
    assert page.next_cursor is not None
    # Default is newest-first.
    assert page.items[0].created_at > page.items[-1].created_at


async def test_paginate_keyset_caps_limit_at_max(repo: BaseRepository[_Widget]) -> None:
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(MAX_LIST_LIMIT + 5):
        await repo.add(_widget(f"w{i}", created_at=base_time + timedelta(milliseconds=i)))

    page = await repo._paginate_keyset(
        select(_Widget),
        order_by=_Widget.created_at,
        tiebreaker=_Widget.id,
        limit=10_000,
    )

    assert len(page.items) == MAX_LIST_LIMIT
    assert page.next_cursor is not None


async def test_paginate_keyset_follows_cursor_across_all_pages(
    repo: BaseRepository[_Widget],
) -> None:
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    total = 12
    for i in range(total):
        await repo.add(_widget(f"w{i}", created_at=base_time + timedelta(milliseconds=i)))

    seen: list[uuid.UUID] = []
    cursor: tuple[datetime, uuid.UUID] | None = None
    for _ in range(total):  # generous upper bound on page count
        page = await repo._paginate_keyset(
            select(_Widget),
            order_by=_Widget.created_at,
            tiebreaker=_Widget.id,
            after=cursor,
            limit=5,
        )
        seen.extend(item.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == total
    assert len(set(seen)) == total  # no duplicates, nothing skipped


async def test_paginate_keyset_breaks_ties_on_equal_order_by(
    repo: BaseRepository[_Widget],
) -> None:
    tied_time = datetime(2026, 1, 1, tzinfo=UTC)
    a = await repo.add(_widget("a", created_at=tied_time))
    b = await repo.add(_widget("b", created_at=tied_time))

    page_one = await repo._paginate_keyset(
        select(_Widget), order_by=_Widget.created_at, tiebreaker=_Widget.id, limit=1
    )
    assert len(page_one.items) == 1
    assert page_one.next_cursor is not None

    page_two = await repo._paginate_keyset(
        select(_Widget),
        order_by=_Widget.created_at,
        tiebreaker=_Widget.id,
        after=page_one.next_cursor,
        limit=1,
    )
    assert len(page_two.items) == 1
    assert page_two.next_cursor is None

    seen_ids = {page_one.items[0].id, page_two.items[0].id}
    assert seen_ids == {a.id, b.id}
