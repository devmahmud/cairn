"""Guardrails: input rail -> LLM -> output rail (BLUEPRINT.md §3.12).

No-op by default (`GUARDRAILS_ENABLED=false`) -- boots and this template's
test suite runs with zero guardrail credentials. See `rails.py` for the
`input_rail`/`output_rail` entry points `agents/chat/nodes/input_rail.py`/
`output_rail.py` call.
"""

from __future__ import annotations

from core.guardrails.models import RailVerdict
from core.guardrails.rails import input_rail, output_rail

__all__ = ["RailVerdict", "input_rail", "output_rail"]
