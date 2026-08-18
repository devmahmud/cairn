"""Deliberately not a generic field__op filter DSL -- concrete repositories write their own typed select() query methods; this covers only get/add/delete/paginate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from core.db.base import Base

# MAX_LIST_LIMIT caps a caller-supplied limit so a client can't force an unbounded scan.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


@dataclass(frozen=True, slots=True)
class Page[ModelT: Base]:
    """next_cursor is the (order_by, tiebreaker) pair of the last item on this page; pass it back as `after` for the next page, or None if this was the last."""

    items: list[ModelT]
    next_cursor: tuple[Any, Any] | None


class BaseRepository[ModelT: Base]:
    """Not a unit of work -- callers own the session's transaction boundary; nothing here calls session.commit()."""

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    async def get(self, pk: Any) -> ModelT | None:
        return await self.session.get(self.model, pk)

    async def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    async def _paginate_keyset(
        self,
        stmt: Select[tuple[ModelT]],
        *,
        order_by: InstrumentedAttribute[Any],
        tiebreaker: InstrumentedAttribute[Any],
        after: tuple[Any, Any] | None = None,
        limit: int | None = None,
        descending: bool = True,
    ) -> Page[ModelT]:
        """Orders by (order_by, tiebreaker) for a stable total order even when order_by alone has ties -- a plain OFFSET cursor would risk skipping/repeating rows."""
        effective_limit = max(1, min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT))

        if after is not None:
            seek = tuple_(order_by, tiebreaker)
            target = tuple_(*after)
            stmt = stmt.where(seek < target if descending else seek > target)

        order_clause = (
            (order_by.desc(), tiebreaker.desc())
            if descending
            else (order_by.asc(), tiebreaker.asc())
        )
        stmt = stmt.order_by(*order_clause).limit(effective_limit + 1)

        rows = list((await self.session.execute(stmt)).scalars().all())
        has_more = len(rows) > effective_limit
        items = rows[:effective_limit]

        next_cursor: tuple[Any, Any] | None = None
        if has_more and items:
            last = items[-1]
            next_cursor = (getattr(last, order_by.key), getattr(last, tiebreaker.key))

        return Page(items=items, next_cursor=next_cursor)
