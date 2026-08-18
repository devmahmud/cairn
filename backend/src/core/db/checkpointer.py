"""AsyncPostgresSaver (langgraph-checkpoint-postgres, MIT) -- never langgraph-api/langgraph-cli, which are Elastic License 2.0 / commercial."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from core.config import Settings
from core.db.engine import to_psycopg_dsn

#: AsyncPostgresSaver reads columns by name -- AsyncConnection[DictRow] keeps the pool's static type honest about its dict_row row_factory.
_DictRowConnectionPool = AsyncConnectionPool[AsyncConnection[DictRow]]


def build_checkpointer_pool(settings: Settings) -> _DictRowConnectionPool:
    """Needs its own psycopg pool, separate from the app's asyncpg engine; kwargs match AsyncPostgresSaver.from_conn_string's documented-correct settings."""
    kwargs: dict[str, Any] = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
    return AsyncConnectionPool(
        to_psycopg_dsn(settings.DATABASE_URL),
        connection_class=AsyncConnection[DictRow],
        open=False,
        kwargs=kwargs,
    )


def build_checkpointer(pool: _DictRowConnectionPool) -> AsyncPostgresSaver:
    return AsyncPostgresSaver(conn=pool)
