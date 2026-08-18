"""Structured logging; censor_sensitive_data redacts sensitive-looking event_dict keys only -- it is not a PII/DLP scanner and won't catch a secret embedded in a free-text message."""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

import structlog

# Substring match, deliberately broad -- a false-positive redaction is free, a missed one isn't.
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
    # Normalize -/_ so header-style (x-api-key) and Python-style (api_key) keys both hit the same markers.
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _censor_value(key: str, value: Any) -> Any:
    # Sensitivity only applies at a leaf, so a redacted list/dict keeps its shape instead of collapsing to a scalar.
    if isinstance(value, Mapping):
        return {str(k): _censor_value(str(k), v) for k, v in value.items()}
    if isinstance(value, str | bytes):
        # str/bytes are themselves Sequences -- must be handled as a leaf before the generic branch iterates char-by-char.
        return _REDACTED if _is_sensitive_key(key) else value
    if isinstance(value, Sequence):
        return [_censor_value(key, item) for item in value]
    return _REDACTED if _is_sensitive_key(key) else value


def censor_sensitive_data(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """Redacts any event_dict entry whose key looks sensitive, recursively."""
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
