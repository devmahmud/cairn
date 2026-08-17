"""Output guardrail hook -- real rails, no-op unless `GUARDRAILS_ENABLED` (BLUEPRINT.md §3.6, §3.12).

The mirror of `input_rail.py`: delegates to `core/guardrails/rails.py::
output_rail` (PII redaction + optional Granite Guardian classification)
over `state["answer"]`. Every branch (`answer`/`rag`/`tool`/`guardrail`)
converges on this node before `END` (§3.6's diagram), so it's the single
choke point for the final answer text.

**Streaming caveat** -- see `core/guardrails/rails.py`'s module docstring:
by the time this node runs, the branch that produced `state["answer"]` has
already streamed it over SSE. This node's redaction reaches what gets
*persisted* (via the turn's `final_state`, `modules/chat/chat_stream.py`),
not bytes already on the wire.
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
from core.guardrails.rails import output_rail

_BLOCKED_OUTPUT_MESSAGE = (
    "I generated a response, but it didn't pass a safety check, so I can't "
    "show it. Please try rephrasing your question."
)


@register
class OutputRailNode(GraphNode[ChatState]):
    name = "output_rail"

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
        original = state.get("answer") or ""
        verdict = await output_rail(
            original,
            behavior_config=self._behavior_config,
            app_settings=self._settings,
            guardian_model_factory=self._guardian_model_factory,
        )

        if verdict.blocked:
            return {
                "answer": _BLOCKED_OUTPUT_MESSAGE,
                "citations": [],
                "error": "output_rail_blocked",
            }
        if verdict.text != original:
            return {"answer": verdict.text}
        return {}
