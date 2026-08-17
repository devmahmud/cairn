"""Unit tests for `core.prompts.langfuse_client.build_langfuse_prompt_client` (BLUEPRINT.md §3.5).

`Langfuse(...)` never touches the network at construction time (only on the
first actual `get_prompt`/flush call), so building a real client here with
throwaway credentials stays a "unit -- no network" test per §3.11.
"""

from __future__ import annotations

from core.config import Settings
from core.prompts.langfuse_client import build_langfuse_prompt_client


def test_returns_none_when_langfuse_prompts_disabled() -> None:
    settings = Settings(LANGFUSE_PROMPTS=False)

    assert build_langfuse_prompt_client(settings) is None


def test_builds_a_client_when_langfuse_prompts_enabled() -> None:
    settings = Settings(
        LANGFUSE_PROMPTS=True,
        LANGFUSE_PUBLIC_KEY="pk-test",
        LANGFUSE_SECRET_KEY="sk-test",
        LANGFUSE_HOST="http://localhost:3000",
    )

    client = build_langfuse_prompt_client(settings)

    assert client is not None
    assert hasattr(client, "get_prompt")
