"""Builds the LangGraph checkpointer (BLUEPRINT.md §3.3, §3.6, §8 step 5).

`AsyncPostgresSaver` (from `langgraph-checkpoint-postgres`, MIT --
`langgraph-api`/`langgraph-cli`, Elastic License 2.0 and commercial, are
never imported here or anywhere in this template, per §1's license note)
persists graph execution state per `thread_id` (`str(conversation_id)`,
§3.6). It needs its own `psycopg` (v3) connection pool, separate from this
app's `asyncpg`-backed SQLAlchemy engine (`core/db/engine.py`) -- two
different drivers pointed at the same database, hence `to_psycopg_dsn`.

The pool is built with `open=False`: constructing it (a lazy
`providers.Singleton` in `core/di/container.py`) never touches the network
by itself (offline-first, design principle #4). `main.py`'s lifespan opens
the pool and calls `AsyncPostgresSaver.setup()` (idempotent -- creates the
checkpoint tables on first run, no-ops after) once at app startup, and
closes the pool on shutdown.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from core.config import Settings
from core.db.engine import to_psycopg_dsn

#: `AsyncPostgresSaver` is typed against a dict-row connection specifically
#: (it reads columns by name) -- `connection_class=AsyncConnection[DictRow]`
#: below (psycopg's connection classes are runtime-subscriptable for exactly
#: this reason) makes the pool's *static* type agree with the `row_factory`
#: it's actually configured with at runtime, instead of the two silently
#: drifting apart.
_DictRowConnectionPool = AsyncConnectionPool[AsyncConnection[DictRow]]


def build_checkpointer_pool(settings: Settings) -> _DictRowConnectionPool:
    """Build (but don't open) the connection pool `AsyncPostgresSaver` uses.

    Kept separate from `build_checkpointer` below so `main.py`'s lifespan
    can `await pool.open()` / `await pool.close()` around the app's
    lifetime without reaching into the `AsyncPostgresSaver` instance itself.
    `autocommit=True, prepare_threshold=0, row_factory=dict_row` matches
    `AsyncPostgresSaver.from_conn_string`'s own connection kwargs -- the
    documented-correct settings for this saver, whether or not you go
    through its convenience constructor.
    """
    kwargs: dict[str, Any] = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
    return AsyncConnectionPool(
        to_psycopg_dsn(settings.DATABASE_URL),
        connection_class=AsyncConnection[DictRow],
        open=False,
        kwargs=kwargs,
    )


def build_checkpointer(pool: _DictRowConnectionPool) -> AsyncPostgresSaver:
    return AsyncPostgresSaver(conn=pool)
