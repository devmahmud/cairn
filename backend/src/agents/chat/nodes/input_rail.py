"""A block doesn't short-circuit the graph -- it clears input and sets error="input_rail_blocked", which route.py redirects to guardrail; classify still runs once on the empty input (documented, harmless)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel

from agents.base import GraphNode
from agents.chat.nodes._protocols import BehaviorSource
from agents.chat.state import ChatState
from agents.registry import register
from core.config import Settings, settings
from core.guardrails.rails import input_rail


@register
class InputRailNode(GraphNode[ChatState]):
    name = "input_rail"

    def __init__(
        self,
        *,
        behavior_config: BehaviorSource,
        app_settings: Settings = settings,
        guardian_model_factory: Callable[[Settings], BaseChatModel] | None = None,
    ) -> None:
        self._behavior_config = behavior_config
        self._settings = app_settings
        self._guardian_model_factory = guardian_model_factory

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        original = state.get("input", "")
        verdict = await input_rail(
            original,
            behavior_config=self._behavior_config,
            app_settings=self._settings,
            guardian_model_factory=self._guardian_model_factory,
        )

        if verdict.blocked:
            return {"input": "", "error": "input_rail_blocked"}
        if verdict.text != original:
            return {"input": verdict.text}
        return {}
