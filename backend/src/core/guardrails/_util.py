"""Private helpers shared within `core/guardrails/` only."""

from __future__ import annotations


def content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content) if content is not None else ""
