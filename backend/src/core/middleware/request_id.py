"""Request-id middleware (BLUEPRINT.md §3.9).

Pure ASGI, not `BaseHTTPMiddleware`: `BaseHTTPMiddleware` has to buffer the
whole response to hand it to your callback, which breaks the SSE streaming
endpoints this template exists to serve (v1's `LoggingApiRoute` re-read
bodies and broke on streams -- §3.9). This middleware never touches the
response body; it only rewrites headers on the outgoing
`http.response.start` ASGI message.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope)
        request_id = incoming.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
