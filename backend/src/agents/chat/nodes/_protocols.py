"""Protocol, not a hard dependency on BehaviorConfig -- route.py/classify.py/rag.py only ever call .get(name)."""

from __future__ import annotations

from typing import Any, Protocol


class BehaviorSource(Protocol):
    async def get(self, name: str) -> dict[str, Any]: ...
