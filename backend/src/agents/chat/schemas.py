"""Structured-output schemas for the chat graph (BLUEPRINT.md §3.6, §8 step 5).

Passed to `BaseChatModel.with_structured_output(...)` -- a different concern
from `chat/state.py`'s `TypedDict` graph state: these are per-*call* forced
output shapes, not the graph's running state.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClassifyResult(BaseModel):
    """One forced-tool-call classification of a user turn (§3.6's `classify`)."""

    intent: str = Field(
        description=(
            "The single best-matching intent name from the provided list. "
            "Use 'unclear' if nothing fits or the request is ambiguous."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How confident you are in `intent`, from 0.0 (guessing) to 1.0 (certain).",
    )
