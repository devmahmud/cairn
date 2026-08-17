"""`PromptEngine` -- resolves a prompt template by name (BLUEPRINT.md §3.5).

Two-tier resolution per §3.5:
1. If `LANGFUSE_PROMPTS=true`: fetch by label (`production`/`prod-a`/
   `prod-b`) from the self-hosted Langfuse instance.
2. Fallback to the bundled `config/prompts/*.j2` files (this module).

This is the file-only fallback half, wired for real today (§8 step 3) so
the DI container's shape (`core/di/container.py`) composes and is
testable; the Langfuse-fetch branch and `watchfiles` hot reload land in
§8 step 4 -- see the `TODO` below for the exact seam that step fills in.
"""

from __future__ import annotations

from core.prompts.loader import FileSystemJ2Loader


class PromptEngine:
    def __init__(self, loader: FileSystemJ2Loader) -> None:
        self._loader = loader

    async def render(self, name: str, **context: object) -> str:
        # TODO(§8 step 4, §3.5): when `settings.LANGFUSE_PROMPTS` is true,
        # fetch the prompt by label from Langfuse first, falling back to
        # `self._loader` on a miss/outage (preserves offline-first); also
        # add `watchfiles`-driven cache invalidation here so an edited
        # `.j2` file is picked up without a restart.
        return self._loader.render(name, **context)
