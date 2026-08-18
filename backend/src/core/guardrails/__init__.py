"""No-op by default (GUARDRAILS_ENABLED=false) -- boots and the test suite run with zero guardrail credentials."""

from __future__ import annotations

from core.guardrails.models import RailVerdict
from core.guardrails.rails import input_rail, output_rail

__all__ = ["RailVerdict", "input_rail", "output_rail"]
