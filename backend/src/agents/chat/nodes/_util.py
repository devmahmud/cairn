"""Small helpers shared by the LLM-calling worker nodes (`answer.py`, `rag.py`).

Private to `agents/chat/nodes/` (leading underscore, not registered as a
node) -- not part of the graph's own shape, just avoids duplicating a couple
of one-liners across the two nodes that render the same system prompt and
normalize an `AIMessage`'s content the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def content_to_text(content: Any) -> str:
    """Normalize a `BaseMessage.content` (str, or a list of content blocks) to `str`."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "".join(parts)
    return str(content)


def today_iso() -> str:
    return datetime.now(UTC).date().isoformat()
