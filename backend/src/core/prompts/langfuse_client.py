"""Constructs the (optional) Langfuse client used for prompt fetching (BLUEPRINT.md §3.5).

Isolated in its own module so `core/prompts/engine.py` depends only on the
`LangfusePromptClient` Protocol it declares, never the concrete `langfuse`
SDK. Nothing here runs unless `LANGFUSE_PROMPTS=true` -- offline-first boot
with zero external credentials (design principle #4) means the common case
never imports the SDK at all.
"""

from __future__ import annotations

from typing import cast

import structlog

from core.config import Settings
from core.prompts.engine import LangfusePromptClient

logger = structlog.get_logger(__name__)


def build_langfuse_prompt_client(settings: Settings) -> LangfusePromptClient | None:
    """Build a Langfuse client for prompt fetching, or `None` if the tier is off.

    Deliberately never raises: a missing/invalid `LANGFUSE_PUBLIC_KEY` or
    `LANGFUSE_SECRET_KEY`, or an unreachable self-hosted `LANGFUSE_HOST`,
    disables the *client* (it logs a warning and every `get_prompt()` call
    raises cleanly) rather than the *process* -- `PromptEngine` catches that
    per-call failure and falls back to the bundled `config/prompts/*.j2`
    file, which is the whole point of the two-tier design (§3.5, offline-
    first). Gated on `LANGFUSE_PROMPTS` specifically (not `LANGFUSE_ENABLED`,
    which governs LLM tracing, a separate concern wired in a later scaffold
    step) so prompt fetching and tracing can be toggled independently.
    """
    if not settings.LANGFUSE_PROMPTS:
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning(
            "prompt_engine.langfuse_prompts_enabled_but_sdk_missing",
            hint="`langfuse` is a declared backend dependency -- check your install.",
        )
        return None
    client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY or None,
        secret_key=settings.LANGFUSE_SECRET_KEY or None,
        host=settings.LANGFUSE_HOST or None,
        # Prompt fetching, not tracing -- don't spin up an OTel span
        # exporter just to fetch prompt text. `LANGFUSE_ENABLED` wires a
        # separate, tracing-enabled client for `get_llm()`'s callbacks
        # (§3.6, a later scaffold step).
        tracing_enabled=False,
    )
    # The real SDK's `get_prompt` returns `TextPromptClient | ChatPromptClient`
    # (chat-type `.compile()` returns a message list, not `str`); we always
    # pass `type="text"` in `engine.py`, so `LangfusePromptClient`'s narrower
    # Protocol -- `.compile(**kwargs) -> str` -- is the true contract for how
    # this codebase calls it.
    return cast(LangfusePromptClient, client)
