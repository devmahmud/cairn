"""Zero-dependency layer 1 of every rail -- always runs first; patterns come from config/behavior/guardrails.yaml via BehaviorConfig."""

from __future__ import annotations

import re

from core.guardrails._protocols import BehaviorSource


async def matches_deterministic_denylist(
    text: str, *, behavior_config: BehaviorSource
) -> str | None:
    """Return a short reason string for the first matching pattern/marker, or `None`."""
    config = await behavior_config.get("guardrails")

    for pattern in config.get("deny_patterns", []):
        if re.search(pattern, text):
            return f"deny_pattern:{pattern}"

    for marker in config.get("delimiter_markers", []):
        if marker in text:
            return f"delimiter_marker:{marker}"

    return None
