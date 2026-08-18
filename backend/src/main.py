"""FastAPI entrypoint; run with src/ as the import root, so modules import as core.config, not src.core.config."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.cors import CORSMiddleware

from core.config import settings
from core.db.engine import engine
from core.di.container import container
from core.errors.handlers import register_exception_handlers
from core.limits.rate_limit import limiter
from core.middleware.request_id import RequestIDMiddleware
from core.observability.logging import configure_logging
from core.prompts.watcher import watch_and_reload
from modules.chat.sse import register_sse_schema
from routers import api_router

configure_logging(json_logs=settings.ENVIRONMENT != "local")
logger = structlog.get_logger(__name__)

# Lazy DI providers: importing container here doesn't touch the network; router.py imports this same instance, not a second Container().


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("app.startup", environment=settings.ENVIRONMENT)

    # Tier 3 config: prompts/behavior files are watched in every environment, not just local -- edits apply on the next request.
    hot_reload_tasks = [
        asyncio.create_task(
            watch_and_reload(f"{settings.CONFIG_DIR}/prompts", container.loader().reload)
        ),
        asyncio.create_task(
            watch_and_reload(f"{settings.CONFIG_DIR}/behavior", container.behavior_config().reload)
        ),
    ]

    # AsyncPostgresSaver owns and migrates its own tables, deliberately not via Alembic, so it can never race the app's own migrations.
    checkpointer_pool = container.checkpointer_pool()
    await checkpointer_pool.open()
    await container.checkpointer().setup()

    yield

    for task in hot_reload_tasks:
        task.cancel()
    await asyncio.gather(*hot_reload_tasks, return_exceptions=True)

    await checkpointer_pool.close()
    await engine.dispose()
    # None whenever REDIS_URL is unset -- nothing to close in that case.
    redis_client = container.redis_client()
    if redis_client is not None:
        await redis_client.aclose()
    logger.info("app.shutdown")


app = FastAPI(
    title="Cairn",
    description="A durable, checkpointed foundation for building agent chat apps.",
    version="0.1.0",
    lifespan=lifespan,
)

# Fail-fast backstop: never allow "*" with credentials enabled.
if "*" in settings.cors_allow_origins_list:
    raise RuntimeError(
        "CORS_ALLOW_ORIGINS must not contain '*': this app allows "
        "credentialed cross-origin requests, and pairing that with a "
        "wildcard origin is both rejected by browsers and an open CORS "
        "misconfiguration."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pure-ASGI, not BaseHTTPMiddleware -- see core/middleware/request_id.py for why.
app.add_middleware(RequestIDMiddleware)

# No-op unless RATE_LIMIT_PER_MIN is set; only modules/chat/router.py's @chat_rate_limit decorator actually enforces anything.
app.state.limiter = limiter
# slowapi's handler is typed narrower (RateLimitExceeded) than add_exception_handler expects -- a real variance mismatch, not a bug here.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

register_exception_handlers(app)

Instrumentator().instrument(app).expose(app, include_in_schema=False)

app.include_router(api_router)

# SSE responses bypass response_model, so this merges ChatSSEEvent's union into /openapi.json for the frontend's generated types.
register_sse_schema(app)
