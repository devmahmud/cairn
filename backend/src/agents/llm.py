"""get_llm(role) is the one place a graph node reaches for a model client -- point OPENAI_BASE_URL at LiteLLM/Ollama/vLLM, or leave blank for OpenAI directly."""

from __future__ import annotations

from functools import lru_cache

import structlog
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agents.config import role_config
from core.config import settings

logger = structlog.get_logger(__name__)


def get_llm(role: str = "answer") -> ChatOpenAI:
    """max_retries=3 is the client-side retry for one call, distinct from (and complementary to) LangGraph's node-level RetryPolicy which re-runs the whole node."""
    cfg = role_config(role)
    return ChatOpenAI(
        model=cfg.model,
        temperature=cfg.temperature,
        api_key=SecretStr(settings.OPENAI_API_KEY or "not-needed-for-local-model"),
        base_url=settings.OPENAI_BASE_URL or None,
        max_retries=3,
        timeout=cfg.timeout,
        callbacks=_langfuse_callbacks(),
    )


def _langfuse_callbacks() -> list[BaseCallbackHandler]:
    if not settings.LANGFUSE_ENABLED:
        return []
    handler = _tracing_callback_handler()
    return [handler] if handler is not None else []


@lru_cache(maxsize=1)
def _tracing_callback_handler() -> BaseCallbackHandler | None:
    """Cached (including None) so a Langfuse outage logs once, not per get_llm() call; disables tracing only, not the LLM call itself."""
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning(
            "llm.langfuse_enabled_but_sdk_missing",
            hint="`langfuse` (and `langchain`, its LangChain-integration "
            "dependency) are declared backend dependencies -- check your install.",
        )
        return None
    try:
        # Registers a tracing client under this public key so CallbackHandler(public_key=...) below can look it up; separate from langfuse_client.py's.
        Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY or None,
            secret_key=settings.LANGFUSE_SECRET_KEY or None,
            host=settings.LANGFUSE_HOST or None,
        )
        return CallbackHandler(public_key=settings.LANGFUSE_PUBLIC_KEY or None)
    except Exception:
        logger.warning("llm.langfuse_tracing_client_unavailable", exc_info=True)
        return None
