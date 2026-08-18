"""Duplicates agents/chat/nodes/_protocols.py's identical Protocol -- core/ must not depend on agents/, so structural typing does the sharing instead of an import."""

from __future__ import annotations

from typing import Any, Protocol


class BehaviorSource(Protocol):
    async def get(self, name: str) -> dict[str, Any]: ...
