"""Guardrail rails: input -> LLM -> output (BLUEPRINT.md §3.6, §3.12).

`input_rail`/`output_rail` are what `agents/chat/nodes/input_rail.py`/
`output_rail.py` call -- true no-ops (return the text unchanged, never
blocked) whenever `GUARDRAILS_ENABLED=false` (the offline-first default,
design principle #4), so this module never imports Presidio or reaches a
guard-model endpoint unless a deployment opts in.

When enabled, both rails run the same layers, in order, stopping at the
first block:

1. **Deterministic denylist/delimiter check** (`patterns.py`) -- zero
   dependencies, cheapest to evaluate, catches the crudest override/
   delimiter-injection attempts (OWASP LLM01) without a model call.
2. **PII redaction** (`pii.py`, Presidio) -- runs on whatever survives step
   1, so even a message this step doesn't block still isn't carrying raw
   PII forward.
3. **Guard-model classification** (`granite_guardian.py`) -- only when
   `GUARDIAN_MODEL_BASE_URL` is configured (blank -> skip, same degrade as
   `RERANKER_BASE_URL`); a positive verdict blocks.

Retrieved RAG passages are untrusted input for this module's purposes
(OWASP LLM01's indirect-injection case, §3.12) -- a caller that wants
retrieved context screened runs it through `input_rail` too, exactly like
the user's own message; this module doesn't distinguish the two.

**Streaming caveat for `output_rail`, stated plainly** (matching this
template's stance, §3.12: "say so loudly"): by the time `output_rail`
(`agents/chat/nodes/output_rail.py`) runs, the branch node that produced
`state["answer"]` (`answer`/`rag`/`guardrail`) has already streamed that
text to the client over SSE -- either token-by-token (`stream_mode=
["messages","custom"]`) or as one delta at branch completion
(`modules/chat/chat_stream.py`'s `_EventTranslator`). `output_rail`'s
redaction reaches what gets **persisted** (`messages.content`, via the
turn's `final_state`) and therefore anything read later (REST history,
future LLM context, audit) -- it cannot retroactively un-send bytes already
on the wire. A deployment that needs a stronger before-the-first-byte
guarantee has to buffer each branch's full output before streaming any of
it, which trades away real-time token streaming (§3.7); redacting PII at
the source (prompts, retrieved context) is the more targeted fix.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from langchain_core.language_models import BaseChatModel

from core.config import Settings, settings
from core.guardrails import granite_guardian, patterns, pii
from core.guardrails._protocols import BehaviorSource
from core.guardrails.models import RailVerdict

logger = structlog.get_logger(__name__)


async def input_rail(
    text: str,
    *,
    behavior_config: BehaviorSource,
    app_settings: Settings = settings,
    guardian_model_factory: Callable[[Settings], BaseChatModel] | None = None,
) -> RailVerdict:
    return await _run_rail(
        text,
        direction="input",
        behavior_config=behavior_config,
        app_settings=app_settings,
        guardian_model_factory=guardian_model_factory,
    )


async def output_rail(
    text: str,
    *,
    behavior_config: BehaviorSource,
    app_settings: Settings = settings,
    guardian_model_factory: Callable[[Settings], BaseChatModel] | None = None,
) -> RailVerdict:
    return await _run_rail(
        text,
        direction="output",
        behavior_config=behavior_config,
        app_settings=app_settings,
        guardian_model_factory=guardian_model_factory,
    )


async def _run_rail(
    text: str,
    *,
    direction: str,
    behavior_config: BehaviorSource,
    app_settings: Settings,
    guardian_model_factory: Callable[[Settings], BaseChatModel] | None,
) -> RailVerdict:
    if not app_settings.GUARDRAILS_ENABLED or not text:
        return RailVerdict(text=text, blocked=False)

    deny_reason = await patterns.matches_deterministic_denylist(
        text, behavior_config=behavior_config
    )
    if deny_reason is not None:
        logger.info("guardrails.denylist_blocked", direction=direction, reason=deny_reason)
        return RailVerdict(text="", blocked=True, reason=deny_reason)

    redacted = pii.redact_pii(text)

    if app_settings.GUARDIAN_MODEL_BASE_URL:
        verdict = await granite_guardian.classify(
            redacted,
            direction=direction,
            app_settings=app_settings,
            model_factory=guardian_model_factory,
        )
        if verdict.blocked:
            logger.info(
                "guardrails.guard_model_blocked", direction=direction, reason=verdict.reason
            )
            return RailVerdict(text="", blocked=True, reason=verdict.reason)

    return RailVerdict(text=redacted, blocked=False)
