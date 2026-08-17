"""Small helpers shared by the LLM-calling worker nodes (`answer.py`, `rag.py`, `tool.py`).

Private to `agents/chat/nodes/` (leading underscore, not registered as a
node) -- not part of the graph's own shape, just avoids duplicating a couple
of one-liners across the nodes that render the same system prompt, normalize
an `AIMessage`'s content the same way, and (§3.6, §3.7) push incremental
output via LangGraph's custom stream writer.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.config import get_stream_writer


def stream_writer_or_noop() -> Callable[[dict[str, Any]], None]:
    """`get_stream_writer()`, or a no-op outside any graph run.

    LangGraph always provides a writer (real when `stream_mode` includes
    `"custom"`, a no-op otherwise) to a node executing as part of
    `.ainvoke()`/`.astream()` on a *compiled graph* -- this only guards the
    one case that isn't such a run: a node under direct unit test, called as
    a bare Python object with no graph around it at all (e.g.
    `tests/unit/test_rag_node.py`), where `get_stream_writer()` raises
    `RuntimeError` instead.
    """
    try:
        return get_stream_writer()
    except RuntimeError:
        return lambda _chunk: None


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
