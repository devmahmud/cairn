"""Guardrail decision node -- shape-correct today, `interrupt()` wiring is step 7 (BLUEPRINT.md §3.6, §3.12).

`route` sends a turn here today only for the `unclear` intent (per
`config/behavior/routing.yaml`) -- there is no real guardrail *verdict* to
act on yet (Presidio/NeMo Guardrails/Granite Guardian land in §8 step 7), so
this node cannot yet decide "refuse" vs. "ask a human" vs. "let it through".
Until then it's deterministic: it always returns the same clarification
message, and it never calls `interrupt()`.

The graph shape this node sits in is already exactly what real HITL needs,
though: one node, called once per visit, returning one state update. A
LangGraph `interrupt()` call pauses the graph at that point and resumes --
via the checkpointer, on the next invocation with the same `thread_id`
(§3.3, §3.6) -- with whatever value a human/reviewer supplies. Slotting that
in later is a body change in this file, not a graph rewire; the call site is
marked below.
"""

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


@register
class GuardrailNode(GraphNode[ChatState]):
    name = "guardrail"

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        # Step 7 belongs here: something like
        #     verdict = await self._guard_model.classify(state["input"])
        #     if verdict.requires_human_review:
        #         decision = interrupt({"reason": verdict.reason, "input": state["input"]})
        #         ...branch on the resumed human decision...
        # `interrupt()` comes from `langgraph.types`; deliberately not
        # imported here since it's unused until step 7 wires a real verdict
        # to gate it on.
        message = AIMessage(content=_CLARIFICATION_MESSAGE)
        return {
            "messages": [message],
            "answer": _CLARIFICATION_MESSAGE,
            "citations": [],
            "abstained": True,
        }
