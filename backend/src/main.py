"""FastAPI application entrypoint (BLUEPRINT.md §3.9, §8 step 2).

Run via `fastapi dev src/main.py` (local -- see the Makefile's `run` target)
or `uvicorn main:app --app-dir src` (Docker, see `Dockerfile`); both resolve
`src/` as the import root, so first-party modules import as `core.config`,
not `src.core.config`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.cors import CORSMiddleware

from core.config import settings
from core.db.engine import engine
from core.errors.handlers import register_exception_handlers
from core.middleware.request_id import RequestIDMiddleware
from core.observability.logging import configure_logging
from routers import api_router

configure_logging(json_logs=settings.ENVIRONMENT != "local")
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("app.startup", environment=settings.ENVIRONMENT)

    # LangGraph's `AsyncPostgresSaver` owns and migrates its own checkpoint
    # tables at startup (BLUEPRINT.md §3.3) -- deliberately NOT via Alembic,
    # so it can never race or duplicate the app's own migrations. The
    # checkpointer instance itself is wired through the DI container in a
    # later scaffold step (agents, §8 step 5); this is the exact call-site
    # it belongs at once it exists:
    # await checkpointer.setup()

    yield

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
