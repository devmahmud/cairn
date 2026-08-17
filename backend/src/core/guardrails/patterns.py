"""Deterministic denylist/delimiter check (BLUEPRINT.md §3.12, OWASP LLM01).

Zero-dependency layer 1 of every rail (`core/guardrails/rails.py`) -- always
runs first when `GUARDRAILS_ENABLED=true`, catches the crudest prompt-
override/delimiter-injection attempts without a guard-model call. Patterns
live in `config/behavior/guardrails.yaml`, read through the same
`BehaviorConfig` (`core/behavior/loader.py`) every other rules file in this
template goes through -- hot-reloaded (§3.2 tier 3) and overridable
cluster-wide via the `config_overrides` table (§3.2 tier 2, keys
`behavior.guardrails.*`).
"""

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
