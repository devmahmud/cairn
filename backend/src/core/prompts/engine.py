"""Two-tier prompt resolution: Langfuse-by-label first if enabled, falling back to the bundled .j2 file on any error. name is the local file's path; the Langfuse name is derived by dropping ".j2"."""

from __future__ import annotations

import asyncio
from typing import Protocol

import structlog

from core.prompts.loader import FileSystemJ2Loader

logger = structlog.get_logger(__name__)


class PromptCompiler(Protocol):
    def compile(self, **kwargs: object) -> str: ...


class LangfusePromptClient(Protocol):
    """Protocol, not a hard dependency on langfuse.Langfuse -- keeps this importable without the SDK even when LANGFUSE_PROMPTS=false."""

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
        # Falls back to the local file even if langfuse_prompts_enabled=True was passed without a client, instead of raising on None.
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
