"""Lets a test/CLI/eval harness look up "the classify node's class" by name, without knowing it lives in agents.chat.nodes.classify."""

from __future__ import annotations

from typing import Any

from agents.base import GraphNode

_REGISTRY: dict[str, type[GraphNode[Any]]] = {}


def register[NodeT: GraphNode[Any]](node_cls: type[NodeT]) -> type[NodeT]:
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
