"""Raised instead of a bare HTTPException so error handling is centralized in handlers.py rather than scattered try/except blocks per router."""

from __future__ import annotations


class AppError(Exception):
    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.error_code
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"


class ValidationAppError(AppError):
    status_code = 422
    error_code = "validation_error"


class UnauthorizedError(AppError):
    status_code = 401
    error_code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    error_code = "forbidden"


class ServiceUnavailableError(AppError):
    status_code = 503
    error_code = "service_unavailable"
