"""Unit tests for `core.behavior.loader.BehaviorConfig` (BLUEPRINT.md §3.2, §3.5, §8 step 4).

Loads the real bundled `config/behavior/routing.yaml` as a sanity check that
the shipped example behavior file is valid, alongside override-merge and
hot-reload coverage against `tmp_path` fixtures (fixture-backed, no
network, per §3.11 -- `overrides` is a plain in-memory fake here, never the
Postgres-backed `RuntimeConfig`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.behavior.loader import BehaviorConfig
from core.errors.exceptions import NotFoundError, ValidationAppError

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_BEHAVIOR_DIR = _BACKEND_ROOT / "config" / "behavior"


async def test_bundled_routing_config_loads_with_docs_assistant_intents() -> None:
    config = BehaviorConfig(_BUNDLED_BEHAVIOR_DIR)

    routing = await config.get("routing")

    assert routing["default_route"] == "rag"
    assert isinstance(routing["confidence_threshold"], float)
    intent_names = {intent["name"] for intent in routing["intents"]}
    assert {"product_question", "greeting", "web_search", "unclear"} <= intent_names


async def test_get_raises_not_found_for_missing_file(tmp_path: Path) -> None:
    config = BehaviorConfig(tmp_path)

    with pytest.raises(NotFoundError):
        await config.get("does_not_exist")


async def test_get_raises_validation_error_for_non_mapping_yaml(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- a\n- b\n")
    config = BehaviorConfig(tmp_path)

    with pytest.raises(ValidationAppError):
        await config.get("list")


async def test_reload_picks_up_edited_file(tmp_path: Path) -> None:
    path = tmp_path / "routing.yaml"
    path.write_text("default_route: rag\n")
    config = BehaviorConfig(tmp_path)

    assert (await config.get("routing"))["default_route"] == "rag"

    path.write_text("default_route: tool\n")
    assert (await config.get("routing"))["default_route"] == "rag"  # still cached

    config.reload()
    assert (await config.get("routing"))["default_route"] == "tool"


class _FakeOverrides:
    def __init__(self, overrides: dict[str, Any]) -> None:
        self._overrides = overrides

    async def get_all(self) -> dict[str, Any]:
        return self._overrides


async def test_overrides_overlay_onto_file_by_dotted_path(tmp_path: Path) -> None:
    (tmp_path / "routing.yaml").write_text(
        "default_route: rag\nconfidence_threshold: 0.55\nnested:\n  value: 1\n"
    )
    overrides = _FakeOverrides(
        {
            "behavior.routing.confidence_threshold": 0.8,
            "behavior.routing.nested.value": 2,
            "behavior.other_file.ignored": True,
        }
    )
    config = BehaviorConfig(tmp_path, overrides=overrides)

    routing = await config.get("routing")

    assert routing["confidence_threshold"] == 0.8
    assert routing["nested"]["value"] == 2
    assert routing["default_route"] == "rag"  # untouched, and no other-file bleed-through


async def test_overrides_do_not_mutate_the_cached_document(tmp_path: Path) -> None:
    (tmp_path / "routing.yaml").write_text("default_route: rag\n")
    overrides = _FakeOverrides({"behavior.routing.default_route": "tool"})
    config = BehaviorConfig(tmp_path, overrides=overrides)

    overridden = await config.get("routing")

    assert overridden["default_route"] == "tool"
    assert config._cache["routing"]["default_route"] == "rag"


async def test_no_overrides_source_returns_the_file_as_is(tmp_path: Path) -> None:
    (tmp_path / "routing.yaml").write_text("default_route: rag\n")
    config = BehaviorConfig(tmp_path)

    routing = await config.get("routing")

    assert routing == {"default_route": "rag"}
