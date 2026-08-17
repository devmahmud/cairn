"""File-system Jinja2 prompt-template loader (BLUEPRINT.md §3.5, §2).

Loads `.j2` files from `config/prompts/` (BLUEPRINT.md §2). This is the
file-only half of the two-tier resolution `PromptEngine` (`engine.py`)
performs -- the Langfuse-by-label branch builds on top of this loader
without changing its interface, and falls back to it on a miss/outage.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from core.errors.exceptions import NotFoundError


class FileSystemJ2Loader:
    def __init__(self, base_path: str | Path) -> None:
        self._base_path = Path(base_path)
        self._env = self._build_env()

    def _build_env(self) -> Environment:
        return Environment(
            loader=FileSystemLoader(str(self._base_path)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            # Explicit invalidation via `reload()` (driven by
            # `core/prompts/watcher.py`'s `watchfiles` watch, §3.2 tier 3)
            # rather than Jinja's own per-`get_template()` mtime check --
            # one observable, testable reload path instead of two competing
            # ones, matching this codebase's preference for explicit over
            # implicit (§3.3: "no generic filter DSL").
            auto_reload=False,
            cache_size=-1,
        )

    def render(self, name: str, **context: object) -> str:
        """Render `<base_path>/<name>` with `context`.

        `name` should include the `.j2` extension (e.g. `"chat/answer.j2"`)
        -- explicit over implicit, matching this template's stance against
        magic elsewhere (§3.3's "no generic filter DSL").
        """
        try:
            template = self._env.get_template(name)
        except TemplateNotFound as exc:
            raise NotFoundError(
                f"Prompt template {name!r} not found under {self._base_path}."
            ) from exc
        return template.render(**context)

    def reload(self) -> None:
        """Drop every cached/compiled template so the next `render()` re-reads from disk.

        Wired as the `on_change` callback the `watchfiles`-driven background
        watcher calls whenever a file under `base_path` changes (§3.2 tier
        3) -- see `core/prompts/watcher.py` and `main.py`'s lifespan.
        """
        self._env = self._build_env()
