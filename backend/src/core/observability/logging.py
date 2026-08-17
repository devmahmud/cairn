"""Structured logging setup (BLUEPRINT.md §3.9).

JSON everywhere except local dev, where a readable console renderer is
worth the trade-off. `structlog.contextvars.merge_contextvars` is what
makes the request-id middleware's `bind_contextvars(request_id=...)` show
up on every log line emitted while handling that request, without threading
a request id through every function call by hand.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(*, json_logs: bool) -> None:
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
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
