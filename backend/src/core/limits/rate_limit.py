"""`slowapi` per-user/IP rate limit on `/chat` (BLUEPRINT.md §3.10, §3.13).

`RATE_LIMIT_PER_MIN=0` (the local-dev default) turns this off entirely --
`chat_rate_limit` below is a plain pass-through decorator in that case, so
`modules/chat/router.py` always applies the *same* decorator name
regardless of whether limiting is active. This mirrors
`core/security/current_user.py`'s `AUTH_ENABLED` branch: decide once, at
import time, from a tier-1 static `Settings` value (§3.2: boot-time,
immutable for the process's life), rather than special-casing every call
site.

Keyed by the caller's identity when it can be read cheaply, IP otherwise:
`_rate_limit_key` decodes the bearer JWT's `sub` claim **without verifying
the signature or expiry** -- this is a bucketing key for rate limiting, not
an authentication decision (that already happens, separately, in
`core.security.current_user.get_current_user_id`), so a forged/garbage
token just falls back to IP-keyed limiting rather than being trusted for
anything.
"""

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
