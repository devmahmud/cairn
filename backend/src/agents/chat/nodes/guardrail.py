"""Guardrail decision node -- distinguishes a real block from low-confidence routing (BLUEPRINT.md §3.6, §3.12).

`route` sends a turn here for two different reasons, and this node now
tells them apart (§8 step 7):
- **`unclear` intent** (`config/behavior/routing.yaml`, classifier
  confidence below threshold or no matching intent) -- a friendly
  clarification prompt, same as before this step.
- **`input_rail`/`output_rail` blocked** (`state["error"] ==
  "input_rail_blocked"` or `"output_rail_blocked"`, `core/guardrails/`,
  §3.12) -- a plain refusal, not a clarification invitation; a caller whose
  message tripped the denylist or a guard-model verdict shouldn't be
  encouraged to "just rephrase it" the way an ambiguous-but-benign message
  should.

`interrupt()`-based human-in-the-loop review is still not wired here --
there is no reviewer/queue in this template to hand a paused turn to yet.
The graph shape already supports it (one node, called once per visit,
returning one state update; `interrupt()` pauses and resumes via the
checkpointer on the next invocation with the same `thread_id`, §3.3, §3.6)
-- slotting it in later is a further body change in this file, not a graph
rewire; the call site is marked below.
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
_REFUSAL_MESSAGE = "I can't help with that request."

_BLOCKED_BY_RAIL_ERRORS = frozenset({"input_rail_blocked", "output_rail_blocked"})


@register
class GuardrailNode(GraphNode[ChatState]):
    name = "guardrail"

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        # A future HITL step belongs here: something like
        #     verdict = await self._guard_model.classify(state["input"])
        #     if verdict.requires_human_review:
        #         decision = interrupt({"reason": verdict.reason, "input": state["input"]})
        #         ...branch on the resumed human decision...
        # `interrupt()` comes from `langgraph.types`; deliberately not
        # imported here since it's unused until a real reviewer/queue backs it.
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
            # Passed through (not just used locally) so the streamer's
            # translator can tell a real block apart from a merely-`unclear`
            # routing outcome and surface `GuardrailEvent(action="refuse")`
            # + a matching `ErrorEvent` instead of `"clarify"`
            # (`modules/chat/chat_stream.py`'s `_handle_branch_completion`,
            # §3.7's `GuardrailEvent.action` docstring: '"refuse"/"review"
            # are step 7's to add').
            update["error"] = blocked_error
        return update
