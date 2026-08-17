"""Unit tests for `agents.chat.nodes.route.RouteNode` (BLUEPRINT.md §3.6).

No LLM, no graph -- exactly the "discoverable/testable in isolation" case
`agents/registry.py`'s docstring describes. Uses a hand-rolled
`BehaviorConfig`-shaped fake (matching `core/behavior/loader.py`'s own
`OverridesSource` Protocol pattern) rather than the real file-backed one, so
these tests don't depend on `config/behavior/routing.yaml`'s actual
contents changing out from under them.
"""

from __future__ import annotations

from typing import Any

from agents.chat.nodes.route import RouteNode
from agents.chat.state import ChatState


class _FakeBehaviorConfig:
    def __init__(self, routing: dict[str, Any]) -> None:
        self._routing = routing

    async def get(self, name: str) -> dict[str, Any]:
        assert name == "routing"
        return self._routing


_ROUTING = {
    "default_route": "rag",
    "confidence_threshold": 0.5,
    "intents": [
        {"name": "greeting", "route": "answer"},
        {"name": "web_search", "route": "tool"},
        {"name": "unclear", "route": "guardrail"},
    ],
}


def _state(*, intent: str | None, confidence: float | None) -> ChatState:
    return {"intent": intent, "confidence": confidence}


async def test_matched_intent_above_threshold_uses_its_mapped_route() -> None:
    node = RouteNode(behavior_config=_FakeBehaviorConfig(_ROUTING))

    result = await node(_state(intent="web_search", confidence=0.9))

    assert result == {"route": "tool"}


async def test_matched_intent_below_threshold_falls_through_to_default_route() -> None:
    node = RouteNode(behavior_config=_FakeBehaviorConfig(_ROUTING))

    # Confidence below `confidence_threshold` (0.5) -- even though
    # `web_search` is a known intent mapped to `tool`, `routing.yaml`'s own
    # rule ("below confidence_threshold ... falls through to
    # default_route") wins.
    result = await node(_state(intent="web_search", confidence=0.2))

    assert result == {"route": "rag"}


async def test_unknown_intent_falls_through_to_default_route() -> None:
    node = RouteNode(behavior_config=_FakeBehaviorConfig(_ROUTING))

    result = await node(_state(intent="never_registered", confidence=0.99))

    assert result == {"route": "rag"}


async def test_missing_intent_falls_through_to_default_route() -> None:
    node = RouteNode(behavior_config=_FakeBehaviorConfig(_ROUTING))

    result = await node(_state(intent=None, confidence=None))

    assert result == {"route": "rag"}


async def test_invalid_default_route_falls_back_to_rag() -> None:
    routing = {**_ROUTING, "default_route": "not_a_real_branch"}
    node = RouteNode(behavior_config=_FakeBehaviorConfig(routing))

    result = await node(_state(intent="never_registered", confidence=0.99))

    assert result == {"route": "rag"}
