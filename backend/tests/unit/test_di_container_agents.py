"""Sanity check: the DI container's agent-runtime providers resolve without
touching the network (BLUEPRINT.md §3.4, §8 step 5).

Mirrors `test_di_container_prompt_engine.py`'s style/scope. `checkpointer`
builds an `AsyncConnectionPool` with `open=False` (§8 step 5's
`core/db/checkpointer.py`) and `chat_agent` builds the whole compiled graph
-- both are pure object construction, no I/O, so this resolves cleanly with
no Postgres/Redis/model API reachable, matching every other provider's
offline-first construction story.
"""

from __future__ import annotations

from agents.chat.agent import ChatAgent
from core.di.container import Container
from modules.embedding.service import OpenAIEmbeddingService
from modules.retrieval.protocol import RetrievalService


def test_container_embedding_and_retrieval_services_resolve() -> None:
    container = Container()

    embedding_service = container.embedding_service()
    retrieval_service = container.retrieval_service()

    assert isinstance(embedding_service, OpenAIEmbeddingService)
    assert isinstance(retrieval_service, RetrievalService)


async def test_container_checkpointer_resolves_without_opening_a_connection() -> None:
    # `AsyncPostgresSaver.__init__` calls `asyncio.get_running_loop()`, so
    # this (and the test below) must run inside an event loop -- `async def`
    # is enough, `pytest-asyncio`'s `asyncio_mode = "auto"` (pyproject.toml)
    # provides one.
    container = Container()

    pool = container.checkpointer_pool()
    checkpointer = container.checkpointer()

    assert pool.closed  # `open=False` -- nothing has connected yet
    assert checkpointer is not None


async def test_container_chat_agent_resolves_and_is_a_singleton() -> None:
    container = Container()

    agent = container.chat_agent()

    assert isinstance(agent, ChatAgent)
    assert container.chat_agent() is agent
