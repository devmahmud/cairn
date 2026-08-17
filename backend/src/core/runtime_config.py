"""Tier 2 of the config system: Postgres-backed runtime overrides (BLUEPRINT.md §3.2).

`config_overrides(key, value, updated_at)` (created by the first Alembic
migration) is the kill-switch / feature-toggle plane -- a plain `UPDATE`
flips behavior cluster-wide with no redeploy (e.g. `tool.web_search.enabled`,
`guardrails.strict`). Reads are served from an in-process cache refreshed on
a short TTL rather than hitting Postgres on every call site; that is simpler
than `LISTEN/NOTIFY` for a template and is correct enough for flags that
don't need sub-second propagation. `refresh()` is exposed for callers (e.g.
an admin endpoint after an `UPDATE`) that want tighter propagation than the
TTL alone gives.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)

DEFAULT_TTL_SECONDS = 5.0


class RuntimeConfig:
    """Cached accessor over the `config_overrides` table.

    One instance per process, backed by the app's async engine (wired
    through the DI container in a later scaffold step). Values are stored as
    `jsonb`, so reads come back as already-decoded Python bool/str/int/float/
    dict/list -- no ad hoc string parsing at call sites.
    """

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
        """Return a snapshot of every currently-cached override.

        Used by callers that need to filter by key *prefix* (e.g.
        `core/behavior/loader.py` pulling every `behavior.<name>.*` row to
        overlay onto a hot-reloaded YAML file, §3.2/§3.5) rather than one
        known key at a time.
        """
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
            # A transient DB blip shouldn't take a feature flag (and
            # everything gated on it) down with it -- keep serving the
            # last-known-good cache and try again on the next TTL window.
            logger.warning("runtime_config.refresh_failed", exc_info=True)
            self._loaded_at = time.monotonic()
