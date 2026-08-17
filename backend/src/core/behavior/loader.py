"""`BehaviorConfig` -- loads `config/behavior/*.yaml` (BLUEPRINT.md §3.2, §3.5).

Sibling of `core/prompts/`: this is tier 3 ("Prompts/behavior files + hot
reload") for the YAML half rather than the `.j2` half -- rules, guardrail
patterns, and (per §3.6) the deterministic `routing.yaml` a later scaffold
step's `route` graph node reads. Two things layer on top of the raw parsed
YAML, both per §3.2/§3.5:

1. **Hot reload.** `reload()` drops the cached parse; wired as the
   `on_change` callback for the same `watchfiles`-driven watcher
   (`core/prompts/watcher.py`) that reloads prompt templates, so editing a
   behavior file needs no rebuild/restart either.
2. **Runtime overrides.** Rows in the `config_overrides` table (tier 2,
   `core/runtime_config.py`) keyed `behavior.<name>.<dotted.path>` are
   overlaid onto the file's parsed dict on every `get()` call -- a flag flip
   there takes effect cluster-wide without touching the file at all, and
   without a redeploy.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Protocol

import yaml

from core.errors.exceptions import NotFoundError, ValidationAppError


class OverridesSource(Protocol):
    """The slice of `core.runtime_config.RuntimeConfig` this loader needs.

    A `Protocol`, not a hard dependency on the concrete class, so this
    module is testable with a plain in-memory fake -- no Postgres, matching
    this codebase's "unit -- fixture-backed, no network" stance (§3.11).
    """

    async def get_all(self) -> dict[str, Any]: ...


class BehaviorConfig:
    def __init__(self, base_path: str | Path, *, overrides: OverridesSource | None = None) -> None:
        self._base_path = Path(base_path)
        self._overrides = overrides
        self._cache: dict[str, dict[str, Any]] = {}

    async def get(self, name: str) -> dict[str, Any]:
        """Return `<base_path>/<name>.yaml`'s contents, with overrides applied.

        `name` excludes the `.yaml` extension (e.g. `"routing"`), matching
        the key prefix (`behavior.routing.*`) overrides are looked up under.
        """
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
        """Drop the cached parse so the next `get()` re-reads from disk.

        Wired as the `on_change` callback the `watchfiles`-driven background
        watcher calls whenever a file under `base_path` changes (§3.2 tier
        3) -- see `core/prompts/watcher.py` and `main.py`'s lifespan.
        """
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
    """Set `target[a][b][...] = value` for `dotted_path == "a.b...."`.

    Intermediate keys are created (as dicts) if missing, and replaced (not
    merged) if present but not themselves a dict -- an override always wins.
    """
    *parents, leaf = dotted_path.split(".")
    node = target
    for part in parents:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[leaf] = value
