"""FastAPI exception handlers (BLUEPRINT.md §3.9).

Registered via `add_exception_handler`, not a `BaseHTTPMiddleware` wrapper --
the latter has to buffer the response to hand your callback a chance to
inspect/replace it, which breaks the SSE streaming endpoints this template
exists to serve (§3.7). Exception handlers run inside Starlette's exception
middleware, which never buffers a streaming response.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from core.errors.exceptions import AppError

logger = structlog.get_logger(__name__)


def _error_body(*, error_code: str, detail: str) -> dict[str, Any]:
    return {"error": {"code": error_code, "detail": detail}}


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    logger.info(
        "app_error",
        error_code=exc.error_code,
        detail=exc.detail,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(error_code=exc.error_code, detail=exc.detail),
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_error", path=request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_body(error_code="internal_error", detail="An unexpected error occurred."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register typed-error and catch-all JSON exception handlers.

    Order matters: FastAPI/Starlette dispatch to the most specific matching
    handler, so registering both `AppError` and `Exception` is safe --
    `AppError` subclasses hit `_handle_app_error`, everything else falls
    through to the catch-all 500 handler instead of an unhandled traceback
    reaching the client.
    """
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
