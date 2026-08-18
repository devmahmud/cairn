"""Guardrail decision node: input_rail/output_rail blocks get a plain refusal, not a "just rephrase" clarification invitation."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from agents.base import GraphNode
from agents.chat.state import ChatState
from agents.registry import register

_CLARIFICATION_MESSAGE = (
    "I'm not sure I understood that. Could you rephrase your question, or "
    "ask something about the documentation directly?"
)
_REFUSAL_MESSAGE = "I can't help with that request."

_BLOCKED_BY_RAIL_ERRORS = frozenset({"input_rail_blocked", "output_rail_blocked"})


@register
class GuardrailNode(GraphNode[ChatState]):
    name = "guardrail"

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        # HITL entry point: langgraph.types.interrupt() would pause/resume here via the checkpointer once a reviewer/queue exists.
        blocked_error = state.get("error")
        blocked_error = blocked_error if blocked_error in _BLOCKED_BY_RAIL_ERRORS else None
        message = _REFUSAL_MESSAGE if blocked_error else _CLARIFICATION_MESSAGE

        update: dict[str, Any] = {
            "messages": [AIMessage(content=message)],
            "answer": message,
            "citations": [],
            "abstained": True,
        }
        if blocked_error is not None:
            # Passed through so the streamer's translator can distinguish a real block (action="refuse") from unclear routing.
            update["error"] = blocked_error
        return update
