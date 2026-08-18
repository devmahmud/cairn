"""DI composition root -- import the module-level `container` instance, not `Container` the class, so singletons like the checkpointer pool are shared."""

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
    # Seeded once at import time -- runtime overrides go through config_overrides/watchfiles, not this container.
    config = providers.Object(settings)

    # Injected into ChatStreamer so a turn opens its own short transactions rather than pinning a request-scoped session.
    sessionmaker = providers.Object(SessionLocal)
    # Raw engine for collaborators needing a connection rather than a session-per-unit-of-work -- today just runtime_config.
    db_engine = providers.Object(engine)

    loader = providers.Singleton(
        FileSystemJ2Loader,
        base_path=f"{settings.CONFIG_DIR}/prompts",
    )
    # None whenever LANGFUSE_PROMPTS=false -- PromptEngine degrades to loader alone, never touching the network.
    langfuse_prompt_client = providers.Singleton(build_langfuse_prompt_client, settings=config)
    prompt_engine = providers.Singleton(
        PromptEngine,
        loader=loader,
        langfuse_client=langfuse_prompt_client,
        langfuse_prompts_enabled=settings.LANGFUSE_PROMPTS,
        label=settings.LANGFUSE_PROMPT_LABEL,
    )

    # Tier 2 config: config_overrides kill-switch/feature-toggle plane; behavior_config overlays onto the matching hot-reloaded YAML.
    runtime_config = providers.Singleton(RuntimeConfig, engine=db_engine)
    behavior_config = providers.Singleton(
        BehaviorConfig,
        base_path=f"{settings.CONFIG_DIR}/behavior",
        overrides=runtime_config,
    )

    # Constructor defaults already read settings directly; touches no network until a query actually calls it.
    embedding_service = providers.Singleton(OpenAIEmbeddingService)

    # USE_LOCAL_RETRIEVAL=true returns the zero-dep fixture service, never touching sessionmaker/embedding_service's network path.
    retrieval_service = providers.Singleton(
        build_retrieval_service,
        use_local=settings.USE_LOCAL_RETRIEVAL,
        rerank=settings.RERANK_ENABLED,
        sessionmaker=sessionmaker,
        embedding_service=embedding_service,
    )

    # Built open=False -- no network at construction; main.py's lifespan is the one place that opens it and runs setup().
    checkpointer_pool = providers.Singleton(build_checkpointer_pool, settings=config)
    checkpointer = providers.Singleton(build_checkpointer, pool=checkpointer_pool)

    chat_agent = providers.Singleton(
        ChatAgent,
        prompt_engine=prompt_engine,
        retrieval_service=retrieval_service,
        checkpointer=checkpointer,
        behavior_config=behavior_config,
    )

    # redis_client is None whenever REDIS_URL is unset; ChatStreamer.durable_enabled checks stream_bus to fall back to simple mode.
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
