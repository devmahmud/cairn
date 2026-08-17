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


def to_psycopg_dsn(database_url: str) -> str:
    """Strip SQLAlchemy's `+asyncpg` driver qualifier for `psycopg` consumers.

    `Settings.DATABASE_URL` is a SQLAlchemy URL (`postgresql+asyncpg://...`)
    -- correct for this module's own `asyncpg`-backed engine, but LangGraph's
    `AsyncPostgresSaver` (`langgraph-checkpoint-postgres`) is built on
    `psycopg` (v3), a different driver with its own plain
    `postgresql://...` DSN format (§3.3, §8 step 5's checkpointer provider,
    `core/di/container.py`). Both drivers point at the same database; only
    the connection-string dialect differs.
    """
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


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
