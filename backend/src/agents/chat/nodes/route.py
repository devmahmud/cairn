"""If input_rail blocked this turn, route straight to guardrail regardless of classify's result -- classify still ran (fixed edges) but its output is meaningless for a blocked message."""

from __future__ import annotations

from typing import Any

from agents.base import GraphNode
from agents.chat.nodes._protocols import BehaviorSource
from agents.chat.state import ChatState
from agents.registry import register

#: Must match the branch names agents/chat/graph.py wires out of route's conditional edge.
VALID_ROUTES = frozenset({"answer", "rag", "tool", "guardrail"})


@register
class RouteNode(GraphNode[ChatState]):
    name = "route"

    def __init__(self, *, behavior_config: BehaviorSource) -> None:
        self._behavior_config = behavior_config

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        if state.get("error") == "input_rail_blocked":
            return {"route": "guardrail"}

        routing = await self._behavior_config.get("routing")
        default_route = _coerce_route(routing.get("default_route"), fallback="rag")
        confidence_threshold = float(routing.get("confidence_threshold", 0.0))
        intents_by_name = {
            entry["name"]: entry for entry in routing.get("intents", []) if entry.get("name")
        }

        intent = state.get("intent")
        confidence = state.get("confidence") or 0.0
        matched = intents_by_name.get(intent) if intent else None

        if matched is not None and confidence >= confidence_threshold:
            route = _coerce_route(matched.get("route"), fallback=default_route)
        else:
            route = default_route

        return {"route": route}


def _coerce_route(candidate: object, *, fallback: str) -> str:
    if isinstance(candidate, str) and candidate in VALID_ROUTES:
        return candidate
    return fallback if fallback in VALID_ROUTES else "rag"
