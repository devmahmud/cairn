"""Shared guardrail types (BLUEPRINT.md §3.12)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RailVerdict:
    """One rail's verdict on a piece of text.

    `text` is what the caller should continue with: the (possibly PII-
    redacted) input when `blocked=False`, or `""` when `blocked=True` --
    nothing "safe" survived a block, so there's nothing to pass through
    (`core/guardrails/rails.py`).
    """

    text: str
    blocked: bool
    reason: str | None = None
