"""Thin generic repository base (BLUEPRINT.md §3.3).

Deliberately NOT a generic `field__op` filter DSL -- concrete repositories
(`modules/*/repository.py`) write their own explicit, typed `select()`
query methods (clearer, `mypy`-friendly, supports joins/projections). This
base only covers what's genuinely generic across every entity: get-by-pk,
add, delete, and a keyset-pagination helper a concrete repository's own
`select()` can be run through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from core.db.base import Base

# A list endpoint with no explicit `limit` gets this many rows, never
# "everything" (§3.3: "a default LIMIT on list reads"). `MAX_LIST_LIMIT`
# caps a caller-supplied `limit` so a client can't force an unbounded scan.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


@dataclass(frozen=True, slots=True)
class Page[ModelT: Base]:
    """One page of a keyset-paginated list read.

    `next_cursor` is the `(order_by, tiebreaker)` value pair of the last
    item on this page -- pass it back as `after` to fetch the next page.
    `None` means this was the last page.
    """

    items: list[ModelT]
    next_cursor: tuple[Any, Any] | None


class BaseRepository[ModelT: Base]:
    """Generic get/add/delete + keyset pagination for one ORM entity.

    Not a unit of work -- callers own the session's transaction boundary
    (commit-per-request for REST via `core.db.engine.get_session`, or the
    chat streamer's own short transactions for a turn, §3.3). Nothing here
    calls `session.commit()`.
    """

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
        """Run a concrete repository's own `select()` through keyset (seek)
        pagination, ordered by `(order_by, tiebreaker)` for a stable total
        order even when `order_by` alone has ties (e.g. same-microsecond
        `created_at` values) -- a plain `OFFSET`/single-column cursor would
        risk skipping or repeating rows across pages in that case.

        `stmt` should already carry every filter/join a caller needs (e.g.
        ownership scoping, §3.9) -- this only appends the seek predicate,
        the order, and the limit; it never builds `WHERE` clauses itself.
        """
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
