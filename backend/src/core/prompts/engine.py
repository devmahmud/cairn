"""`PromptEngine` -- resolves a prompt template by name (BLUEPRINT.md §3.5).

Two-tier resolution, degrading gracefully (design principle #4, offline-first):
1. If `settings.LANGFUSE_PROMPTS` is true: fetch by label (`production` by
   default, `LANGFUSE_PROMPT_LABEL`) from the self-hosted Langfuse instance.
   Langfuse's own client already caches successful fetches in-process and
   serves the stale cached copy if a *later* refresh fails -- so this tier
   already covers "Langfuse had a transient blip after already working."
   What it can't cover is a *cold* cache (nothing fetched yet this process)
   hitting an outage on the very first call, which raises. Either way, any
   exception from the Langfuse client falls through to:
2. The bundled `config/prompts/*.j2` file (`FileSystemJ2Loader`) -- the
   offline-first floor that always works with zero external credentials.

`name` is always the local `.j2` file's relative path (e.g.
`"docs_assistant/system.j2"`); the Langfuse-side prompt name is derived by
dropping the `.j2` suffix, so one `render()` call site works regardless of
which tier ultimately serves it.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import structlog

from core.prompts.loader import FileSystemJ2Loader

logger = structlog.get_logger(__name__)


class PromptCompiler(Protocol):
    def compile(self, **kwargs: object) -> str: ...


class LangfusePromptClient(Protocol):
    """The slice of the `langfuse` SDK's client `PromptEngine` needs.

    A `Protocol`, not a hard dependency on `langfuse.Langfuse`, so this
    module -- and anything that imports it -- stays importable (and
    trivially unit-testable with a fake) without the `langfuse` package ever
    touching the network, even in a process where `LANGFUSE_PROMPTS=false`
    (the offline-first default, §3.2).
    """

    def get_prompt(self, name: str, *, label: str, type: str = "text") -> PromptCompiler: ...


class PromptEngine:
    def __init__(
        self,
        loader: FileSystemJ2Loader,
        *,
        langfuse_client: LangfusePromptClient | None = None,
        langfuse_prompts_enabled: bool = False,
        label: str = "production",
    ) -> None:
        self._loader = loader
        self._langfuse_client = langfuse_client
        # Belt-and-suspenders: even if a caller passes
        # `langfuse_prompts_enabled=True` without also passing a client,
        # `render()` should still degrade to the local file instead of
        # raising `AttributeError` on `None`.
        self._langfuse_prompts_enabled = langfuse_prompts_enabled and langfuse_client is not None
        self._label = label

    async def render(self, name: str, **context: object) -> str:
        if self._langfuse_prompts_enabled:
            rendered = await self._render_from_langfuse(name, context)
            if rendered is not None:
                return rendered
        return self._loader.render(name, **context)

    async def _render_from_langfuse(self, name: str, context: dict[str, object]) -> str | None:
        assert self._langfuse_client is not None
        langfuse_name = name.removesuffix(".j2")
        try:
            prompt = await asyncio.to_thread(
                self._langfuse_client.get_prompt,
                langfuse_name,
                label=self._label,
                type="text",
            )
            return prompt.compile(**context)
        except Exception:
            logger.warning(
                "prompt_engine.langfuse_unavailable_falling_back_to_bundled_file",
                name=langfuse_name,
                label=self._label,
                exc_info=True,
            )
            return None
