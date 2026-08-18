"""Process-wide asyncio.Semaphore bounding in-flight generations; lazily built (like other module-level singletons here) rather than at import time."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.config import settings

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, settings.MAX_CONCURRENT_GENERATIONS))
    return _semaphore


@asynccontextmanager
async def limit_concurrent_generations() -> AsyncIterator[None]:
    async with _get_semaphore():
        yield
