"""Loads config/behavior/*.yaml with two layers on top: hot reload via watcher.py, and config_overrides rows keyed "behavior.<name>.<dotted.path>" overlaid on every get()."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Protocol

import yaml

from core.errors.exceptions import NotFoundError, ValidationAppError


class OverridesSource(Protocol):
    async def get_all(self) -> dict[str, Any]: ...


class BehaviorConfig:
    def __init__(self, base_path: str | Path, *, overrides: OverridesSource | None = None) -> None:
        self._base_path = Path(base_path)
        self._overrides = overrides
        self._cache: dict[str, dict[str, Any]] = {}

    async def get(self, name: str) -> dict[str, Any]:
        """name excludes the .yaml extension (e.g. "routing"), matching the override key prefix "behavior.<name>.*"."""
        document = self._load(name)
        if self._overrides is None:
            return document

        prefix = f"behavior.{name}."
        matching = {
            key.removeprefix(prefix): value
            for key, value in (await self._overrides.get_all()).items()
            if key.startswith(prefix)
        }
        if not matching:
            return document

        merged = copy.deepcopy(document)
        for dotted_path, value in matching.items():
            _set_dotted(merged, dotted_path, value)
        return merged

    def reload(self) -> None:
        """Called by watcher.py's on_change callback whenever a file under base_path changes."""
        self._cache.clear()

    def _load(self, name: str) -> dict[str, Any]:
        if name in self._cache:
            return self._cache[name]

        path = self._base_path / f"{name}.yaml"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise NotFoundError(
                f"Behavior config {name!r} not found under {self._base_path}."
            ) from exc

        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            raise ValidationAppError(
                f"Behavior config {name!r} must parse to a YAML mapping, "
                f"got {type(parsed).__name__}."
            )
        self._cache[name] = parsed
        return parsed


def _set_dotted(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    """target[a][b][...] = value for dotted_path == "a.b....". Non-dict intermediate keys are replaced, not merged -- an override always wins."""
    *parents, leaf = dotted_path.split(".")
    node = target
    for part in parents:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[leaf] = value
