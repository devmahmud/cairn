"""Base node abstraction for LangGraph graphs (BLUEPRINT.md §3.6, §8 step 5).

Every concrete node under `agents/chat/nodes/` subclasses `GraphNode`
instead of being a bare function. Three things that buys, all load-bearing
for a template meant to be read and extended:

1. **A stable shape.** `name` + one `__call__(state) -> dict` method is the
   entire contract LangGraph's `StateGraph.add_node` needs (a node is just
   any callable taking the state and returning a partial update) -- a class
   makes constructor-injected dependencies (prompt engine, retrieval
   service, LLM factory, ...) explicit and typed instead of smuggled in via
   closures.
2. **Isolated testability.** A node can be constructed directly with fake
   collaborators and called with a hand-built `state` dict, with no graph,
   checkpointer, or DI container involved -- see e.g.
   `tests/unit/test_route_node.py` / `test_rag_node.py`.
3. **Discoverability.** `agents/registry.py` indexes every `GraphNode`
   subclass by `.name`, so `registry.get_node_class("classify")` (in a test,
   a CLI, or an eval harness) doesn't need to know which module defines it.

Deliberately generic over the state's shape (`Mapping`/`dict`, not the
concrete `agents.chat.state.ChatState` TypedDict) -- this module lives
alongside `llm.py`/`config.py`/`registry.py` as agent-runtime infra that
isn't chat-specific, matching the repository layout's split between
`agents/` (the runtime) and `agents/chat/` (one graph built on it, §2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar


class GraphNode[StateT: Mapping[str, Any]](ABC):
    """One LangGraph node: a name plus an async `state -> partial update` call.

    Generic over the state type (bound, not fixed) so each concrete graph's
    state (e.g. `agents.chat.state.ChatState`) flows through `__call__`'s
    signature without every node having to narrow `Mapping[str, Any]` at the
    parameter (which `mypy` would reject as an unsound override) or
    `cast()` inside the method body -- `class InputRailNode(GraphNode[ChatState])`
    is enough.
    """

    #: Registered under this key by `@agents.registry.register` and looked
    #: up by `agents/chat/graph.py`'s `StateGraph.add_node(name, ...)`.
    name: ClassVar[str]

    @abstractmethod
    async def __call__(self, state: StateT) -> dict[str, Any]:
        """Run this node once and return the partial state update to merge in.

        Never mutate `state` in place -- return only the keys this node is
        changing; LangGraph merges the update onto the existing state (per
        key reducer, e.g. `messages`' `add_messages`, §3.6).
        """
        raise NotImplementedError
