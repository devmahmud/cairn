"""DI composition root -- singleton graph only (BLUEPRINT.md §3.4).

`dependency-injector` is used for the agent graph + its collaborators
only, because that's the one thing this template also needs OUTSIDE
FastAPI (the CLI eval harness, §3.11). Everything else -- including the
`conversations` REST module -- wires through plain FastAPI `Depends`
(`modules/conversations/router.py`) per §3.4: "pick one wiring model per
concern and don't mix `Provide` and `Depends` for the same kind of
dependency."

What's real today (§8 steps 4-6): `config`, `sessionmaker`, `loader`,
`prompt_engine` (both tiers -- bundled `.j2` files, and the Langfuse-by-
label overlay when `LANGFUSE_PROMPTS=true`), `db_engine`, `runtime_config`,
`behavior_config`, `embedding_service`, `retrieval_service`,
`checkpointer_pool`/`checkpointer`, `chat_agent`, `redis_client`,
`stream_bus`, and `chat_streamer`. As the composition root, this module is
the one sanctioned place that imports "up" from `agents/`/`modules/` into
what's otherwise `core/`'s own layer (§3.1) -- wiring the object graph
together is the whole point of a composition root.

The module also exports a single instantiated `container` (below the class)
-- `main.py`'s lifespan and `modules/chat/router.py`'s `Depends`-wrapped
resolver both import *that* instance, not `Container` the class, so they
share the one set of already-`.open()`ed singletons (the checkpointer pool,
chiefly) rather than each accidentally building its own.
"""

from __future__ import annotations

from dependency_injector import containers, providers

from agents.chat.agent import ChatAgent
from core.behavior.loader import BehaviorConfig
from core.config import settings
from core.db.checkpointer import build_checkpointer, build_checkpointer_pool
from core.db.engine import SessionLocal, engine
from core.prompts.engine import PromptEngine
from core.prompts.langfuse_client import build_langfuse_prompt_client
from core.prompts.loader import FileSystemJ2Loader
from core.runtime_config import RuntimeConfig
from core.stream.resume import build_redis_client, build_stream_bus
from modules.chat.chat_stream import ChatStreamer
from modules.embedding.service import OpenAIEmbeddingService
from modules.retrieval.factory import build_retrieval_service


class Container(containers.DeclarativeContainer):
    # Seeded once at import time -- no `from_dict` refresh; runtime control
    # is the separate `config_overrides` table + `watchfiles` plane (§3.2),
    # not this container.
    config = providers.Object(settings)

    # The same `async_sessionmaker` `core/db/engine.py` exposes -- injected
    # into the chat streamer (§3.3, §8 step 6) so a turn opens its own
    # short transactions instead of pinning a request-scoped session for
    # the whole stream.
    sessionmaker = providers.Object(SessionLocal)
    # The raw async engine, for collaborators that need a connection rather
    # than a session-per-unit-of-work -- today just `runtime_config` (§3.2
    # tier 2, a plain `SELECT` against `config_overrides`, not an ORM
    # unit-of-work).
    db_engine = providers.Object(engine)

    loader = providers.Singleton(
        FileSystemJ2Loader,
        base_path=f"{settings.CONFIG_DIR}/prompts",
    )
    # `None` whenever `LANGFUSE_PROMPTS=false` (the offline-first default) --
    # `PromptEngine` degrades to `loader` alone in that case, never touching
    # the network (§3.5, design principle #4).
    langfuse_prompt_client = providers.Singleton(build_langfuse_prompt_client, settings=config)
    prompt_engine = providers.Singleton(
        PromptEngine,
        loader=loader,
        langfuse_client=langfuse_prompt_client,
        langfuse_prompts_enabled=settings.LANGFUSE_PROMPTS,
        label=settings.LANGFUSE_PROMPT_LABEL,
    )

    # Tier 2 (§3.2): the `config_overrides` kill-switch/feature-toggle
    # plane. `behavior_config` (below) is its first real consumer -- an
    # `UPDATE` keyed `behavior.<name>.<dotted.path>` overlays onto the
    # matching hot-reloaded YAML file without a redeploy.
    runtime_config = providers.Singleton(RuntimeConfig, engine=db_engine)
    behavior_config = providers.Singleton(
        BehaviorConfig,
        base_path=f"{settings.CONFIG_DIR}/behavior",
        overrides=runtime_config,
    )

    # Self-hosted-by-default, OpenAI-compatible embeddings client (§3.8) --
    # `OpenAIEmbeddingService`'s own constructor defaults already read
    # `settings.EMBEDDING_MODEL`/`OPENAI_BASE_URL`/etc., so no kwargs are
    # threaded through here; touches no network until a query actually
    # calls it (offline-first, design principle #4).
    embedding_service = providers.Singleton(OpenAIEmbeddingService)

    # `build_retrieval_service` (§3.8's factory): `USE_LOCAL_RETRIEVAL=true`
    # (the offline-first default) returns the zero-dep fixture service and
    # never touches `sessionmaker`/`embedding_service`'s network path at
    # all; `false` builds the real pgvector-hybrid(+rerank) service.
    retrieval_service = providers.Singleton(
        build_retrieval_service,
        use_local=settings.USE_LOCAL_RETRIEVAL,
        rerank=settings.RERANK_ENABLED,
        sessionmaker=sessionmaker,
        embedding_service=embedding_service,
    )

    # LangGraph's checkpointer (§3.3, §3.6) -- `checkpointer_pool` is built
    # `open=False` (no network at construction, same offline-first stance as
    # every other provider here); `main.py`'s lifespan is the one place that
    # `await`s `.open()` and `AsyncPostgresSaver.setup()` once at startup
    # (see its docstring for exactly why there, not here).
    checkpointer_pool = providers.Singleton(build_checkpointer_pool, settings=config)
    checkpointer = providers.Singleton(build_checkpointer, pool=checkpointer_pool)

    chat_agent = providers.Singleton(
        ChatAgent,
        prompt_engine=prompt_engine,
        retrieval_service=retrieval_service,
        checkpointer=checkpointer,
        behavior_config=behavior_config,
    )

    # Durable streaming's Redis bus (§3.7, §8 step 6). `redis_client` is
    # `None` whenever `REDIS_URL` is unset -- `build_stream_bus` propagates
    # that straight through to `stream_bus`, which is what
    # `ChatStreamer.durable_enabled` checks to fall back to simple-mode
    # streaming instead of erroring. Neither provider touches the network at
    # construction time (offline-first, design principle #4): `redis.from_url`
    # only opens a connection on the first real command.
    redis_client = providers.Singleton(build_redis_client, settings=config)
    stream_bus = providers.Singleton(build_stream_bus, redis_client=redis_client)

    chat_streamer = providers.Factory(
        ChatStreamer,
        chat_agent=chat_agent,
        sessionmaker=sessionmaker,
        stream_bus=stream_bus,
        app_settings=config,
    )


container = Container()
