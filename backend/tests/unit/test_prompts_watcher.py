"""Unit tests for `core.prompts.watcher.watch_and_reload` (BLUEPRINT.md §3.2 tier 3).

Real filesystem events via `watchfiles` against a `tmp_path` -- no network,
just local I/O, so this still fits the "unit" bucket per §3.11.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.prompts.watcher import watch_and_reload


async def test_watch_and_reload_calls_on_change_when_a_file_is_written(tmp_path: Path) -> None:
    calls = 0
    change_seen = asyncio.Event()

    def on_change() -> None:
        nonlocal calls
        calls += 1
        change_seen.set()

    task = asyncio.create_task(watch_and_reload(tmp_path, on_change))
    try:
        # Give `watchfiles` a moment to start watching before writing --
        # otherwise the write can race the watcher's startup.
        await asyncio.sleep(0.2)
        (tmp_path / "new_file.txt").write_text("hello")

        await asyncio.wait_for(change_seen.wait(), timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert calls >= 1


async def test_watch_and_reload_logs_and_continues_when_on_change_raises(tmp_path: Path) -> None:
    calls = 0
    change_seen = asyncio.Event()

    def flaky_on_change() -> None:
        nonlocal calls
        calls += 1
        change_seen.set()
        raise RuntimeError("boom")

    task = asyncio.create_task(watch_and_reload(tmp_path, flaky_on_change))
    try:
        await asyncio.sleep(0.2)
        (tmp_path / "new_file.txt").write_text("hello")

        await asyncio.wait_for(change_seen.wait(), timeout=5)
        # The watch loop must still be alive after `on_change` raised --
        # give it a beat, then confirm the task hasn't exited/crashed.
        await asyncio.sleep(0.1)
        assert not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert calls >= 1
