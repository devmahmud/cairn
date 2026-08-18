"""Shared guardrail types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RailVerdict:
    """text is what the caller continues with -- redacted input if blocked=False, "" if blocked=True (nothing safe survived a block)."""

    text: str
    blocked: bool
    reason: str | None = None
