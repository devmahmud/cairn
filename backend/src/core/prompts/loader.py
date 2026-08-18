"""Loads .j2 files from config/prompts/ -- the file-only half of PromptEngine's two-tier resolution; Langfuse falls back to this on a miss/outage."""

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
            # Explicit invalidation via reload() (driven by watcher.py), not Jinja's own mtime check -- one reload path, not two competing ones.
            auto_reload=False,
            cache_size=-1,
        )

    def render(self, name: str, **context: object) -> str:
        """name should include the .j2 extension (e.g. "chat/answer.j2")."""
        try:
            template = self._env.get_template(name)
        except TemplateNotFound as exc:
            raise NotFoundError(
                f"Prompt template {name!r} not found under {self._base_path}."
            ) from exc
        return template.render(**context)

    def reload(self) -> None:
        """Called by watcher.py's on_change callback whenever a file under base_path changes."""
        self._env = self._build_env()
