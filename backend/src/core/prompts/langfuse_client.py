"""Optional Langfuse client for prompt fetching. Isolated so engine.py depends only on the LangfusePromptClient Protocol, never the langfuse SDK directly."""

from __future__ import annotations

from typing import cast

import structlog

from core.config import Settings
from core.prompts.engine import LangfusePromptClient

logger = structlog.get_logger(__name__)


def build_langfuse_prompt_client(settings: Settings) -> LangfusePromptClient | None:
    """Never raises: a bad key or unreachable host disables the client (logs + None), and PromptEngine falls back to the bundled .j2 files."""
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
        # Prompt fetching only, not tracing -- LANGFUSE_ENABLED wires a separate tracing client for get_llm()'s callbacks.
        tracing_enabled=False,
    )
    # Real SDK returns TextPromptClient | ChatPromptClient; we always pass type="text", so the narrower Protocol here is the true contract.
    return cast(LangfusePromptClient, client)
