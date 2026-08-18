"""Decodes the bearer JWT's sub claim WITHOUT verifying signature/expiry -- a rate-limit bucketing key only, not an auth decision (that happens separately in get_current_user_id); a forged token just falls back to IP-keyed limiting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import jwt
import structlog
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.config import settings

logger = structlog.get_logger(__name__)

_RateLimitDecorator = Callable[[Callable[..., Any]], Callable[..., Any]]


def _rate_limit_key(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        try:
            payload = jwt.decode(
                token,
                options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
            )
        except jwt.PyJWTError:
            payload = {}
        sub = payload.get("sub")
        if isinstance(sub, str) and sub:
            return f"user:{sub}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_rate_limit_key)


def _chat_limit_value() -> str:
    return f"{settings.RATE_LIMIT_PER_MIN}/minute"


chat_rate_limit: _RateLimitDecorator
if settings.RATE_LIMIT_PER_MIN > 0:
    chat_rate_limit = limiter.limit(_chat_limit_value)
else:

    def chat_rate_limit(fn: Callable[..., Any]) -> Callable[..., Any]:
        return fn
