"""FastAPI application entrypoint (BLUEPRINT.md §3.9, §8 step 2).

Run via `fastapi dev src/main.py` (local -- see the Makefile's `run` target)
or `uvicorn main:app --app-dir src` (Docker, see `Dockerfile`); both resolve
`src/` as the import root, so first-party modules import as `core.config`,
not `src.core.config`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.cors import CORSMiddleware

from core.config import settings
from core.db.engine import engine
from core.di.container import Container
from core.errors.handlers import register_exception_handlers
from core.middleware.request_id import RequestIDMiddleware
from core.observability.logging import configure_logging
from core.prompts.watcher import watch_and_reload
from routers import api_router

configure_logging(json_logs=settings.ENVIRONMENT != "local")
logger = structlog.get_logger(__name__)

# The composition root (§3.4). Instantiating it here only builds the
# `Container` object itself -- `dependency-injector` providers are lazy, so
# none of the `_not_yet_implemented` singletons (§8 steps 5-6) are touched
# until something actually resolves them.
container = Container()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("app.startup", environment=settings.ENVIRONMENT)

    # Tier 3 of the config system (§3.2): `config/prompts/*.j2` and
    # `config/behavior/*.yaml` are watched by `watchfiles` in *every*
    # environment (not just local) -- editing a prompt or a routing table
    # takes effect on the next request, no rebuild. Cancelling these tasks
    # on shutdown stops each `watchfiles.awatch` loop cleanly (see
    # `core/prompts/watcher.py`).
    hot_reload_tasks = [
        asyncio.create_task(
            watch_and_reload(f"{settings.CONFIG_DIR}/prompts", container.loader().reload)
        ),
        asyncio.create_task(
            watch_and_reload(f"{settings.CONFIG_DIR}/behavior", container.behavior_config().reload)
        ),
    ]

    # LangGraph's `AsyncPostgresSaver` owns and migrates its own checkpoint
    # tables at startup (BLUEPRINT.md §3.3) -- deliberately NOT via Alembic,
    # so it can never race or duplicate the app's own migrations. The
    # checkpointer instance itself is wired through the DI container in a
    # later scaffold step (agents, §8 step 5); this is the exact call-site
    # it belongs at once it exists:
    # await container.checkpointer().setup()

    yield

    for task in hot_reload_tasks:
        task.cancel()
    await asyncio.gather(*hot_reload_tasks, return_exceptions=True)

    await engine.dispose()
    logger.info("app.shutdown")


app = FastAPI(
    title="Cairn",
    description="A durable, checkpointed foundation for building agent chat apps.",
    version="0.1.0",
    lifespan=lifespan,
)

# Explicit allow-list, never "*" with credentials (BLUEPRINT.md §3.9).
# `CORS_ALLOW_ORIGINS` already defaults to a concrete origin, not a
# wildcard -- this is a hard fail-fast backstop against a misconfigured
# `.env`, not the primary defense.
if "*" in settings.cors_allow_origins_list:
    raise RuntimeError(
        "CORS_ALLOW_ORIGINS must not contain '*': this app allows "
        "credentialed cross-origin requests, and pairing that with a "
        "wildcard origin is both rejected by browsers and an open CORS "
        "misconfiguration (BLUEPRINT.md §3.9)."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pure-ASGI, not `BaseHTTPMiddleware` -- see the module docstring in
# `core/middleware/request_id.py` for why that distinction matters here.
app.add_middleware(RequestIDMiddleware)

register_exception_handlers(app)

Instrumentator().instrument(app).expose(app, include_in_schema=False)

app.include_router(api_router)
