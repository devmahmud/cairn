"""Provider-agnostic LLM factory -- the one swap-point (BLUEPRINT.md §3.6).

`get_llm(role)` is the only place a graph node reaches for a model client.
Point `OPENAI_BASE_URL` at a self-hosted **LiteLLM** proxy (recommended --
budgets/fallback/rate-limit for free, §3.13) or directly at Ollama/vLLM for
a fully local stack; leave it blank to hit OpenAI's own API. Every node
depends on this function (or, in tests, a fake with the same signature)
rather than constructing `ChatOpenAI` itself -- design principle #3,
"provider-agnostic agents: one `get_llm()` swap-point".
"""

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
    """Build a `ChatOpenAI` client configured for `role` (BLUEPRINT.md §3.6).

    `max_retries=3` is the client-side retry for a single call (distinct
    from LangGraph's node-level `RetryPolicy`, which re-runs the whole node
    -- both matter, see `agents/chat/graph.py`). Langfuse tracing is wired
    in as a callback only when `LANGFUSE_ENABLED=true`; the offline-first
    default (`false`) never imports the `langfuse` SDK's callback surface.
    """
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
    """Build (once) the Langfuse LangChain callback handler, or `None`.

    Cached (including a `None` result) so a Langfuse outage is logged once,
    not on every single `get_llm()` call within the process -- mirrors
    `core/prompts/langfuse_client.py`'s degrade-gracefully stance (§3.5):
    `LANGFUSE_ENABLED=true` with an unreachable/misconfigured Langfuse
    disables *tracing*, not the LLM call itself.
    """
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
        # Registers a tracing-enabled client under this public key so
        # `CallbackHandler(public_key=...)` below can look it up. Separate
        # from `core/prompts/langfuse_client.py`'s client -- that one is
        # `tracing_enabled=False` (prompt fetching only); this one traces.
        Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY or None,
            secret_key=settings.LANGFUSE_SECRET_KEY or None,
            host=settings.LANGFUSE_HOST or None,
        )
        return CallbackHandler(public_key=settings.LANGFUSE_PUBLIC_KEY or None)
    except Exception:
        logger.warning("llm.langfuse_tracing_client_unavailable", exc_info=True)
        return None
