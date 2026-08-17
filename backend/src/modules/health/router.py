"""Liveness + readiness probes (BLUEPRINT.md §3.9, §8 step 2).

`/health/live` is a static 200 -- "is the process up," nothing more. It must
never depend on the DB/Redis/LLM, or a downstream outage takes the pod out
of rotation for a reason that has nothing to do with whether the process
itself is alive.

`/health/ready` checks the dependencies this app actually needs to serve a
request right now: Postgres always, Redis only when `REDIS_URL` is set
(`REDIS_URL=""` is a supported, offline-first mode -- §3.2). It deliberately
does **not** call the LLM: that's a network round-trip to a third party on
every readiness probe (orchestrators commonly poll this every few seconds),
which is slow, can rate-limit or cost money, and "is the LLM provider
reachable this instant" isn't what "is this pod ready to accept traffic"
should mean -- a per-request timeout/retry already covers an LLM outage
without coupling it to the probe loop.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from core.config import settings
from core.db.engine import engine
from modules.health.schemas import ComponentCheck, LivenessResponse, ReadinessResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

_CHECK_TIMEOUT_SECONDS = 3.0


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse()


async def _check_database() -> ComponentCheck:
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return ComponentCheck(name="database", ok=True)
    except Exception as exc:
        logger.warning("health.database_check_failed", exc_info=exc)
        return ComponentCheck(name="database", ok=False, detail=str(exc))


async def _check_redis() -> ComponentCheck:
    client = Redis.from_url(settings.REDIS_URL)
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            await client.ping()
        return ComponentCheck(name="redis", ok=True)
    except Exception as exc:
        logger.warning("health.redis_check_failed", exc_info=exc)
        return ComponentCheck(name="redis", ok=False, detail=str(exc))
    finally:
        await client.aclose()


@router.get("/ready", response_model=ReadinessResponse)
async def readiness() -> JSONResponse:
    checks = [await _check_database()]
    if settings.REDIS_URL:
        checks.append(await _check_redis())

    all_ok = all(check.ok for check in checks)
    body = ReadinessResponse(status="ok" if all_ok else "unavailable", checks=checks)
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content=body.model_dump(mode="json"),
    )
