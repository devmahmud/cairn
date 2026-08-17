"""Input guardrail hook -- real rails, no-op unless `GUARDRAILS_ENABLED` (BLUEPRINT.md §3.6, §3.12).

Delegates to `core/guardrails/rails.py::input_rail` -- the deterministic
denylist, PII redaction, and (if `GUARDIAN_MODEL_BASE_URL` is set) Granite
Guardian classification described there. This node's own job is just
threading graph state through that call and reacting to its verdict.

**Not a graph rewire** (per this file's own prior-step docstring, preserved
here): `START -> input_rail -> classify -> route -> ...` is a fixed edge
set, so a blocked input can't short-circuit straight to `guardrail` from
here. Instead: a block clears `state["input"]` (nothing raw/unsafe should
reach `classify`/`answer`/`rag` even as a fallback) and sets
`state["error"] = "input_rail_blocked"`, which `route.py` checks *before*
its normal `routing.yaml` lookup and sends to the `guardrail` branch. The
one real cost of this shape: `classify` still runs once, on an empty
question, before `route` redirects -- a documented tradeoff (a wasted,
harmless LLM call) rather than a graph restructure.
"""

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
