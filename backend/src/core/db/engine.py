"""get_session is for REST endpoints only, one transaction per request -- the chat turn never holds a session across an SSE stream; it opens its own short transactions instead."""

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
    """Strips SQLAlchemy's +asyncpg qualifier -- psycopg (used by the checkpointer) needs the plain postgresql://... DSN form."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency: commit-per-request unit of work for REST routes. Not for the chat streaming turn -- see the module docstring."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
