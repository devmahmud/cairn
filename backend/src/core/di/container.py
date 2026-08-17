"""DI composition root -- singleton graph only (BLUEPRINT.md §3.4).

`dependency-injector` is used for the agent graph + its collaborators
only, because that's the one thing this template also needs OUTSIDE
FastAPI (the CLI eval harness, §3.11). Everything else -- including the
`conversations` REST module -- wires through plain FastAPI `Depends`
(`modules/conversations/router.py`) per §3.4: "pick one wiring model per
concern and don't mix `Provide` and `Depends` for the same kind of
dependency."

What's real today (§8 step 3): `config`, `sessionmaker`, `loader`,
`prompt_engine` (file-only -- the Langfuse overlay lands in §8 step 4).
`embedding_service` / `retrieval_service` / `checkpointer` / `chat_agent`
/ `chat_streamer` are wired with the right *shape* -- provider type, name,
dependency edges -- exactly as later steps (§8 steps 5-6) need it, but
resolving one of them before its step lands raises `NotImplementedError`
immediately (see `_not_yet_implemented` below) rather than silently
importing a class that doesn't exist yet (which would break importing
this module at all) or returning a half-working object.
"""

from __future__ import annotations

from typing import Any, NoReturn

from dependency_injector import containers, providers

from core.config import settings
from core.db.engine import SessionLocal
from core.prompts.engine import PromptEngine
from core.prompts.loader import FileSystemJ2Loader


def _not_yet_implemented(component: str, blueprint_section: str) -> Any:
    """Build the provider callable for a component a later scaffold step adds.

    Keeps the container's shape matching BLUEPRINT.md §3.4 today without
    importing classes that don't exist yet. The returned factory is only
    ever called when something actually resolves this provider (DI
    providers are lazy) -- inert until then.
    """

    def _factory(*_args: object, **_kwargs: object) -> NoReturn:
        raise NotImplementedError(
            f"{component} is wired into the DI container's shape "
            f"(BLUEPRINT.md {blueprint_section}) but not implemented until a "
            "later scaffold step (BLUEPRINT.md §8). See core/di/container.py."
        )

    return _factory


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

    loader = providers.Singleton(
        FileSystemJ2Loader,
        base_path=f"{settings.CONFIG_DIR}/prompts",
    )
    # File-only today; the Langfuse-by-label branch + watchfiles hot reload
    # (§3.5) land in §8 step 4 -- see `core/prompts/engine.py`'s TODO.
    prompt_engine = providers.Singleton(PromptEngine, loader=loader)

    # --- Not yet implemented -- §8 steps 5-6 build these -------------------
    embedding_service = providers.Singleton(
        _not_yet_implemented("embedding_service (OpenAIEmbeddingService)", "§3.8, §8 step 5"),
    )
    retrieval_service = providers.Singleton(
        _not_yet_implemented("retrieval_service (build_retrieval_service)", "§3.8, §8 step 5"),
    )
    checkpointer = providers.Singleton(
        _not_yet_implemented("checkpointer (AsyncPostgresSaver)", "§3.3, §3.6, §8 step 5"),
    )
    chat_agent = providers.Singleton(
        _not_yet_implemented("chat_agent (ChatAgent)", "§3.6, §8 step 5"),
        prompt_engine=prompt_engine,
        retrieval_service=retrieval_service,
        checkpointer=checkpointer,
    )
    chat_streamer = providers.Factory(
        _not_yet_implemented("chat_streamer (ChatStreamer)", "§3.7, §8 step 6"),
        chat_agent=chat_agent,
        sessionmaker=sessionmaker,
    )
