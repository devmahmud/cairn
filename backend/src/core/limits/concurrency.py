"""In-flight-generation concurrency cap (BLUEPRINT.md §3.10, §3.13).

An `asyncio.Semaphore` bounding how many chat turns can be mid-generation
(the LLM/graph work itself, not persistence or SSE tailing) at once,
process-wide. `MAX_CONCURRENT_GENERATIONS` is generous by default (local
dev, single process) -- tune it down for a resource-constrained
deployment. Wired into `modules/chat/chat_stream.py::ChatStreamer._run_turn`,
the one generator both simple- and durable-mode turns share (that method's
own docstring: "Two producer shapes, one core generator").

Lazily constructed (module-level singleton, built on first use) rather than
at import time -- consistent with every other lazily-built singleton in
this codebase (`agents/llm.py::_tracing_callback_handler`,
`core/guardrails/pii.py::_load_engines`), even though an `asyncio.Semaphore`
itself doesn't touch the network; it just avoids adding one more thing that
has to happen correctly at import time for no benefit.
"""

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
