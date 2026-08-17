"""File-system Jinja2 prompt-template loader (BLUEPRINT.md §3.5, §2).

Loads `.j2` files from `config/prompts/` (BLUEPRINT.md §2). This is the
file-only half of the two-tier resolution `PromptEngine` (`engine.py`)
performs -- the Langfuse-by-label branch and `watchfiles` hot reload
(§3.5, §8 step 4) build on top of this loader without changing its
interface.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from core.errors.exceptions import NotFoundError


class FileSystemJ2Loader:
    def __init__(self, base_path: str | Path) -> None:
        self._base_path = Path(base_path)
        self._env = Environment(
            loader=FileSystemLoader(str(self._base_path)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
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
