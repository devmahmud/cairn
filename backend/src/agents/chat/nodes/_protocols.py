"""The slice of `core.behavior.loader.BehaviorConfig` the chat nodes need.

A `Protocol`, not a hard dependency on the concrete class -- same reasoning
`core/behavior/loader.py`'s own `OverridesSource` Protocol documents for
*its* dependency: "testable with a plain in-memory fake -- no Postgres,
matching this codebase's 'unit -- fixture-backed, no network' stance
(§3.11)". `route.py`, `classify.py`, and `rag.py` all only ever call
`.get(name)`, never anything else on `BehaviorConfig`.
"""

from __future__ import annotations

from typing import Any, Protocol


class BehaviorSource(Protocol):
    async def get(self, name: str) -> dict[str, Any]: ...
