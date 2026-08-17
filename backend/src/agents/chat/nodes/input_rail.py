"""Input guardrail hook -- shape-correct, pass-through today (BLUEPRINT.md §3.6, §3.12).

Real guardrail logic -- Presidio PII redaction and Granite Guardian/NeMo
Guardrails prompt-injection screening on `state["input"]` before it reaches
`classify`/`answer`/`rag` (OWASP LLM01/LLM02, §3.12) -- is §8 step 7's job
entirely. This node exists now so the graph's edges
(`START -> input_rail -> classify -> ...`) are final before that step lands,
and so step 7's implementation is a body swap in this one file, not a graph
rewire.

Deliberately not gated on `GUARDRAILS_ENABLED`: there is no guard model
wired in yet to gate, so this is an unconditional pass-through regardless of
the setting -- gating it today would just be dead code with an inert
"enabled" flag.
"""

from __future__ import annotations

from typing import Any

from agents.base import GraphNode
from agents.chat.state import ChatState
from agents.registry import register


@register
class InputRailNode(GraphNode[ChatState]):
    name = "input_rail"

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        # Step 7 belongs here -- redact/screen `state["input"]` and either
        # pass it through unchanged or route straight to `guardrail`
        # (e.g. by setting `route` and short-circuiting classify/route).
        return {}
