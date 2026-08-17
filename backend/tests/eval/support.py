"""Shared builders for the live-LLM eval packs (BLUEPRINT.md §3.11, §8 step 10).

Not a `test_*.py` file -- same "importable support module, not collected by
pytest" pattern as `tests/unit/fakes.py`. `test_scenario_eval.py` and
`test_routing_eval.py` both drive real components against a real, configured
LLM (`OPENAI_API_KEY`/`OPENAI_BASE_URL`) -- these are the two eval packs
`pyproject.toml`'s `eval` marker keeps off the default/CI path (§3.11:
"Cost-incurring LLM-judge eval stays manual"). `test_retrieval_eval.py` and
`test_injection_redteam.py` don't need any of this -- they run fully
offline against `LocalFixtureRetrievalService`/`core.guardrails` directly.
"""

from __future__ import annotations

import pytest

from agents.chat.agent import ChatAgent
from core.behavior.loader import BehaviorConfig
from core.config import settings
from core.prompts.engine import PromptEngine
from core.prompts.loader import FileSystemJ2Loader
from modules.retrieval.fixture import LocalFixtureRetrievalService


def require_live_llm() -> None:
    """Skip (never fail) an eval test when no real model is configured.

    Mirrors `tests/integration/conftest.py`'s `pytest.skip` when no
    reachable Postgres is configured: a developer running `pytest -m eval`
    without `OPENAI_API_KEY`/`OPENAI_BASE_URL` set gets one clear reason
    instead of every scenario/routing case failing on an opaque auth error.
    """
    if not settings.OPENAI_API_KEY and not settings.OPENAI_BASE_URL:
        pytest.skip(
            "No live LLM configured (OPENAI_API_KEY and OPENAI_BASE_URL are both "
            "blank) -- this eval pack calls a real model (BLUEPRINT.md §3.11) and "
            "only runs manually with real credentials set, per pyproject.toml's "
            "`eval` marker."
        )


def build_eval_prompt_engine() -> PromptEngine:
    return PromptEngine(loader=FileSystemJ2Loader(base_path="config/prompts"))


def build_eval_behavior_config() -> BehaviorConfig:
    return BehaviorConfig(base_path="config/behavior")


def build_eval_chat_agent() -> ChatAgent:
    """A real `ChatAgent`: a real LLM (`agents.llm.get_llm`, `ChatAgent`'s
    own default `llm_factory`), fixture-backed retrieval (no Postgres
    needed -- the point of the golden corpus, not the point of this pack),
    and no checkpointer (one-shot eval turns, nothing to resume). Compare
    `tests/unit/test_chat_graph_offline.py`'s identical construction with a
    *fake* LLM instead.
    """
    return ChatAgent(
        prompt_engine=build_eval_prompt_engine(),
        retrieval_service=LocalFixtureRetrievalService(),
        checkpointer=None,
        behavior_config=build_eval_behavior_config(),
    )
