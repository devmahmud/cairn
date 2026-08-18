"""Structured logging setup (BLUEPRINT.md §3.9).

JSON everywhere except local dev, where a readable console renderer is
worth the trade-off. `structlog.contextvars.merge_contextvars` is what
makes the request-id middleware's `bind_contextvars(request_id=...)` show
up on every log line emitted while handling that request, without threading
a request id through every function call by hand.

`censor_sensitive_data` is the processor §3.9 promises ("structlog (JSON,
with a censor_sensitive_data processor -- logs only)") -- `structlog.processors`
ships no such processor itself, so this is a small, deliberately dumb,
key-based one: it redacts any `event_dict` key/nested-mapping-key whose name
*looks* sensitive (`password`, `token`, `secret`, `authorization`, `api_key`,
`cookie`, `jwt`, ...), recursively through dicts/lists, before the renderer
ever turns the event into a line. This is **not** a PII/DLP scanner and
won't catch a secret embedded inside a free-text log message (e.g.
`logger.info(f"got token {tok}")` bypasses it entirely, since it never
becomes its own key) -- the structlog censor is logs-only and is not data
protection, full stop (§3.12); it only helps callers who pass sensitive
values as their own `key=value` kwarg, the normal structlog idiom this
codebase already follows everywhere.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

import structlog

#: Substring match against a lower-cased key -- deliberately broad (catches
#: `password`, `hashed_password`, `refresh_token`, `Authorization`,
#: `x-api-key`, ...) since a false-positive redaction is free; a missed one
#: isn't.
_SENSITIVE_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "cookie",
    "jwt",
)
_REDACTED = "***REDACTED***"


def _is_sensitive_key(key: str) -> bool:
    # Normalize `-`/`_` before matching -- header-style keys (`x-api-key`,
    # `X-Api-Key`) and Python-style keys (`api_key`) both need to hit the
    # same marker list.
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _censor_value(key: str, value: Any) -> Any:
    # Structure (`Mapping`/`Sequence`) is always preserved and recursed into
    # -- sensitivity is only ever applied at a leaf, so a sensitive key whose
    # value is a list/dict gets each of its elements redacted in place
    # (`{"secret": ["a", "b"]}` -> `{"secret": ["***REDACTED***", ...]}`),
    # never collapsed into a single scalar that would silently change the
    # field's shape for downstream JSON log consumers.
    if isinstance(value, Mapping):
        return {str(k): _censor_value(str(k), v) for k, v in value.items()}
    if isinstance(value, str | bytes):
        # `str`/`bytes` are themselves `Sequence`s -- must be checked, and
        # handled as a leaf, before the generic sequence branch below would
        # otherwise iterate them character-by-character.
        return _REDACTED if _is_sensitive_key(key) else value
    if isinstance(value, Sequence):
        return [_censor_value(key, item) for item in value]
    return _REDACTED if _is_sensitive_key(key) else value


def censor_sensitive_data(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """A structlog processor: redact any `event_dict` entry whose key looks
    sensitive, recursively (module docstring above has the full caveat)."""
    return {key: _censor_value(key, value) for key, value in event_dict.items()}


def configure_logging(*, json_logs: bool) -> None:
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        censor_sensitive_data,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
