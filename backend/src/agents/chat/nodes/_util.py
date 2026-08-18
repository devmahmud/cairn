"""Shared helpers for the LLM-calling worker nodes (answer.py, rag.py, tool.py); private to agents/chat/nodes/."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.config import get_stream_writer


def stream_writer_or_noop() -> Callable[[dict[str, Any]], None]:
    """get_stream_writer(), or a no-op -- guards the one case LangGraph doesn't provide a writer: a node called directly under unit test, with no graph around it."""
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
