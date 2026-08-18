"""Passed to with_structured_output() -- distinct from state.py's TypedDict graph state: a per-call forced output shape, not running state."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClassifyResult(BaseModel):
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
