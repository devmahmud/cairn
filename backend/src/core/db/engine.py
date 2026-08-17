"""Async engine + session (BLUEPRINT.md §3.3).

**Transaction rule (the v1 gap this fixes):** `get_session` below is for
REST endpoints only -- one transaction per request, committed once the
handler returns cleanly. The chat turn does **not** use a request-scoped
session: holding one open for the full duration of an SSE stream would pin
a pool connection for as long as the client stays connected. Instead, the
streaming module (added in a later scaffold step) is injected the
`async_sessionmaker` (`SessionLocal`) directly and opens two short-lived
transactions of its own -- one to read turn state at the start, one to
persist results at the end -- neither ever held across the `astream`/LLM
call. The LangGraph checkpointer manages its own connection separately for
graph-state writes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    pool_recycle=1800,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency: commit-per-request unit of work for REST routes.

    Not for the chat streaming turn -- see the module docstring.
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
