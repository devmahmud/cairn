"""The slice of `core.behavior.loader.BehaviorConfig` this package needs.

A local, structural `Protocol` -- not an import of `agents.chat.nodes.
_protocols.BehaviorSource`, which describes the identical shape. `core/`
must not depend on `agents/` (§3.1: "deps flow one way: `agents/modules ->
core`"), even though both Protocols describe the same method and
`core.behavior.loader.BehaviorConfig` satisfies either one automatically --
structural typing needs no shared import for that.
"""

from __future__ import annotations

from typing import Any, Protocol


class BehaviorSource(Protocol):
    async def get(self, name: str) -> dict[str, Any]: ...
