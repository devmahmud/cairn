"""Postgres-backed runtime overrides (config_overrides table), cached in-process on a short TTL rather than LISTEN/NOTIFY -- simpler, and correct enough for flags that don't need sub-second propagation."""

from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)

DEFAULT_TTL_SECONDS = 5.0


class RuntimeConfig:
    """Values are stored as jsonb, so reads come back already-decoded (bool/str/int/float/dict/list) -- no parsing needed at call sites."""

    def __init__(self, engine: AsyncEngine, *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._engine = engine
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, Any] = {}
        self._loaded_at: float = 0.0

    async def get(self, key: str, default: Any = None) -> Any:
        await self._ensure_fresh()
        return self._cache.get(key, default)

    async def get_bool(self, key: str, default: bool = False) -> bool:
        value = await self.get(key, default)
        return bool(value)

    async def get_all(self) -> dict[str, Any]:
        """Snapshot of every cached override -- for callers (e.g. behavior/loader.py) that filter by key prefix rather than fetch one key."""
        await self._ensure_fresh()
        return dict(self._cache)

    async def refresh(self) -> None:
        """Force an immediate reload, bypassing the TTL."""
        async with self._engine.connect() as conn:
            result = await conn.execute(text("SELECT key, value FROM config_overrides"))
            self._cache = {row.key: row.value for row in result}
        self._loaded_at = time.monotonic()
        logger.debug("runtime_config.refreshed", keys=sorted(self._cache))

    async def _ensure_fresh(self) -> None:
        if time.monotonic() - self._loaded_at < self._ttl_seconds:
            return
        try:
            await self.refresh()
        except Exception:
            # A transient DB blip shouldn't take a feature flag down with it -- keep serving the last-known-good cache and retry next TTL window.
            logger.warning("runtime_config.refresh_failed", exc_info=True)
            self._loaded_at = time.monotonic()
