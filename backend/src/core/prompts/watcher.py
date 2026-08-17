"""Generic `watchfiles`-driven hot-reload background task (BLUEPRINT.md §3.2 tier 3).

Tier 3 of the config system covers *both* file kinds this template ships --
`config/prompts/*.j2` (`core/prompts/loader.py`) and `config/behavior/*.yaml`
(`core/behavior/loader.py`) -- "watched by `watchfiles` in every environment;
edit a guardrail/prompt file -> reload, no rebuild." Both loaders need the
same shape of watch loop, so it lives here once rather than twice.
"""

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
    """Call `on_change()` after every batch of filesystem changes under `path`.

    Runs until cancelled -- meant to be wrapped in `asyncio.create_task` from
    the app's lifespan (`main.py`). Cancelling that task on shutdown stops
    the underlying `watchfiles.awatch` iterator cleanly via
    `asyncio.CancelledError`; no extra stop-event plumbing needed for a
    template this size. `on_change` failures are logged and swallowed --one
    bad file edit shouldn't kill the watch loop and silently freeze hot
    reload for every *other* file under `path` too.
    """
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
