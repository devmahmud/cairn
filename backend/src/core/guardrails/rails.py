"""True no-op (text unchanged, never blocked) whenever GUARDRAILS_ENABLED=false -- never imports Presidio or reaches a guard-model endpoint otherwise. Both rails run denylist -> PII redaction -> guard-model classification, in order, stopping at the first block."""

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
    """Redaction here reaches what's persisted; the branch that produced the answer has already streamed it over SSE -- can't un-send bytes on the wire."""
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

    # Runs on whatever survives the denylist, so even an unblocked message doesn't carry raw PII forward.
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
