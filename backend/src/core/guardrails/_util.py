"""Private helpers shared within `core/guardrails/` only."""

from __future__ import annotations


def content_to_text(content: object) -> str:
    """Normalize a `BaseMessage.content` (str, or a list of content blocks)
    to `str` -- the guard-model call's response comes back through the same
    `langchain_core` message shape every LLM call in this codebase does."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content) if content is not None else ""
