"""Sanity check: the DI container's `prompt_engine` provider resolves and
renders a bundled prompt without error (BLUEPRINT.md §3.4, §8 step 4).

Deliberately doesn't exercise `container.behavior_config()` end-to-end here:
that provider's `overrides` dependency is the real, Postgres-backed
`RuntimeConfig`, which belongs in the `integration` suite, not `unit`
(§3.11) -- `tests/unit/test_behavior_config.py` already covers
`BehaviorConfig`'s own logic against an in-memory fake.
"""

from __future__ import annotations

from core.di.container import Container


async def test_container_prompt_engine_renders_bundled_docs_assistant_system_prompt() -> None:
    container = Container()

    engine = container.prompt_engine()
    rendered = await engine.render(
        "docs_assistant/system.j2",
        assistant_name="Cairn Docs Bot",
        product_name="Cairn",
        current_date="2026-08-17",
        tool_names=[],
    )

    assert "Cairn Docs Bot" in rendered
