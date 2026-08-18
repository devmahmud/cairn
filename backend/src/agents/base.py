"""Every node subclasses this instead of being a bare function, so constructor-injected dependencies are explicit/typed and agents/registry.py can look nodes up by name."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar


class GraphNode[StateT: Mapping[str, Any]](ABC):
    """Generic over the state type (bound, not fixed) so e.g. GraphNode[ChatState] narrows __call__'s signature without a cast() in every node."""

    #: Registered under this key by @agents.registry.register, looked up by StateGraph.add_node(name, ...).
    name: ClassVar[str]

    @abstractmethod
    async def __call__(self, state: StateT) -> dict[str, Any]:
        """Never mutate state in place -- return only the changed keys; LangGraph merges the update via each key's reducer."""
        raise NotImplementedError
