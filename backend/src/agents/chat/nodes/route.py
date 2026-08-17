"""`route` -- deterministic Python over `routing.yaml` (BLUEPRINT.md §3.6).

No LLM call: given `classify`'s `{intent, confidence}`, look `intent` up in
`config/behavior/routing.yaml`'s `intents` list (hot-reloaded + runtime-
overridable, §3.2) and dispatch to its mapped `route`. Below
`confidence_threshold`, or on no matching intent, fall through to
`default_route` -- exactly `routing.yaml`'s own header comment, which this
node is the deterministic implementation of. The conditional edge out of
`route` (`agents/chat/graph.py`) reads `state["route"]` this node sets.

One override ahead of that lookup, added in §8 step 7: if `input_rail`
(`agents/chat/nodes/input_rail.py`) blocked this turn (`state["error"] ==
"input_rail_blocked"`), route straight to `guardrail` regardless of
whatever `classify` produced on the now-empty input -- `classify` still
ran (the graph's edges are fixed, §3.6), but its result is meaningless for
a blocked message and must not be allowed to route around the block.
"""

from __future__ import annotations

from typing import Any

from agents.base import GraphNode
from agents.chat.nodes._protocols import BehaviorSource
from agents.chat.state import ChatState
from agents.registry import register

#: Must match the branch names `agents/chat/graph.py` wires out of `route`'s
#: conditional edge -- a `routing.yaml` entry naming anything else falls
#: back to `default_route` rather than sending the graph to a dead end.
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
