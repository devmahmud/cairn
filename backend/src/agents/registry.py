"""A small registry so graph nodes are discoverable/testable in isolation
(BLUEPRINT.md §8 step 5).

`agents/chat/graph.py` still constructs and wires each node explicitly
(explicit, typed, `mypy`-friendly -- matching this codebase's stance against
stringly-typed indirection elsewhere, e.g. `core/repository/base.py`'s "no
generic `field__op` filter DSL"). This registry is the *discovery* path on
top of that: a test, CLI, or eval harness that wants "the `classify` node's
class" doesn't need to know it lives in `agents.chat.nodes.classify`.
"""

from __future__ import annotations

from typing import Any

from agents.base import GraphNode

_REGISTRY: dict[str, type[GraphNode[Any]]] = {}


def register[NodeT: GraphNode[Any]](node_cls: type[NodeT]) -> type[NodeT]:
    """Class decorator: register a `GraphNode` subclass under its `.name`."""
    name = getattr(node_cls, "name", None)
    if not name:
        raise ValueError(f"{node_cls.__name__} must define a non-empty class attribute `name`.")
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not node_cls:
        raise ValueError(
            f"Graph node name {name!r} is already registered to "
            f"{existing.__module__}.{existing.__qualname__}; "
            f"{node_cls.__module__}.{node_cls.__qualname__} can't reuse it."
        )
    _REGISTRY[name] = node_cls
    return node_cls


def get_node_class(name: str) -> type[GraphNode[Any]]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"No graph node registered under {name!r}. Registered: {registered_node_names()}."
        ) from None


def registered_node_names() -> list[str]:
    return sorted(_REGISTRY)
