"""Shared fixtures for backend integration tests (BLUEPRINT.md §3.11).

Needs a real, reachable Postgres. Point `DATABASE_URL` (the same variable
`core.config.Settings` reads) at a scratch database before running:

    DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app_test \\
        uv run pytest -m integration

`_migrated_database` below applies `alembic upgrade head` once per test
session and skips the whole `integration`-marked suite (via `pytest.skip`,
not an error/failure) when that fails -- e.g. no Postgres reachable at
`DATABASE_URL`. Plain `uv run pytest` (no `-m integration`) never needs a
database at all: only files under `tests/integration/` depend on this
fixture.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.config import settings

# `backend/` -- alembic.ini and the `src/` import root both live here.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Truncated (not dropped) before every test for isolation, child-to-parent
# FK order doesn't matter here since `CASCADE` handles it.
_TABLES_TO_RESET = ("messages", "conversations", "users")


@pytest.fixture(scope="session")
def _migrated_database() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(
            "No reachable/migratable Postgres for integration tests "
            f"(DATABASE_URL={settings.DATABASE_URL!r}); `alembic upgrade head` "
            f"failed:\n{result.stdout}\n{result.stderr}"
        )


@pytest_asyncio.fixture
async def db_engine(_migrated_database: None) -> AsyncIterator[AsyncEngine]:
    """A fresh engine per test, truncated to a known-empty state first.

    Function-scoped deliberately: an async engine/connection is bound to
    the event loop it was created in, and pytest-asyncio gives each test
    its own loop by default -- a session-scoped engine would break on the
    second test. Migrations (session-scoped, above) run over a plain
    `subprocess`, which has no event loop to be bound to.
    """
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES_TO_RESET)} RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()
