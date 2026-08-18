"""Same watch loop shape needed by both prompts/*.j2 and behavior/*.yaml hot reload, so it lives here once rather than twice."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog
from watchfiles import awatch

logger = structlog.get_logger(__name__)

OnChange = Callable[[], object | Awaitable[object]]


async def watch_and_reload(path: str | Path, on_change: OnChange) -> None:
    """Runs until cancelled. on_change failures are logged and swallowed -- one bad file edit shouldn't kill the watch loop for every other file under path."""
    watch_path = Path(path)
    await asyncio.to_thread(watch_path.mkdir, parents=True, exist_ok=True)
    async for _changes in awatch(watch_path):
        try:
            result = on_change()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.warning("hot_reload.on_change_failed", path=str(watch_path), exc_info=True)
        else:
            logger.info("hot_reload.reloaded", path=str(watch_path))
