"""Shared helpers for the LLM-calling worker nodes (answer.py, rag.py, tool.py); private to agents/chat/nodes/."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.config import get_stream_writer

from core.config import settings


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


def recent_history(
    messages: Sequence[BaseMessage], *, limit: int = settings.MAX_HISTORY_MESSAGES
) -> list[BaseMessage]:
    """Tail-truncate accumulated turn history so an unbounded conversation can't blow the model's context window or per-turn cost. A fixed window, not summarization -- the simplest thing that keeps a long conversation from growing without bound."""
    return list(messages[-limit:]) if limit > 0 else list(messages)
