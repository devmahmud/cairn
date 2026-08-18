"""add_exception_handler, not BaseHTTPMiddleware -- the latter buffers the response, which breaks the SSE streaming endpoints this template serves."""

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
    """FastAPI dispatches to the most specific matching handler -- AppError subclasses hit _handle_app_error, everything else falls through to the catch-all."""
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
