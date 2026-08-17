"""Output guardrail hook -- shape-correct, pass-through today (BLUEPRINT.md §3.6, §3.12).

The mirror of `input_rail.py`: real logic (a PII pass over `state["answer"]`
and a moderation check before the answer ever reaches SSE, OWASP LLM10,
§3.12) is §8 step 7's job. Every branch (`answer`/`rag`/`tool`/`guardrail`)
converges on this node before `END` (§3.6's diagram), so it's the single
choke point step 7 needs -- already wired today, just inert.
"""

from __future__ import annotations

from typing import Any

from agents.base import GraphNode
from agents.chat.state import ChatState
from agents.registry import register


@register
class OutputRailNode(GraphNode[ChatState]):
    name = "output_rail"

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        # Step 7 belongs here -- redact/moderate `state["answer"]` before it
        # reaches the streamer (§8 step 6).
        return {}
