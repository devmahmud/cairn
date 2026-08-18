"""Redis-backed durable stream bus; replay/tail is keyed by our own monotonic id (not Redis' native ms-seq id)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Any, Protocol

import redis.asyncio as redis
import structlog

from core.config import Settings

logger = structlog.get_logger(__name__)


class RedisStreamClient(Protocol):
    """Protocol, not a hard dependency on redis.asyncio.Redis -- keeps this testable against an in-memory fake."""

    # Loosely typed on purpose: redis-py's stubs use bytes|str|memoryview, and Awaitable[Any] keeps this compatible with real Awaitable[bool] etc. methods.
    def xadd(self, name: str, fields: Any) -> Awaitable[Any]: ...
    def xrange(
        self, name: str, min: str = ..., max: str = ..., count: int | None = ...
    ) -> Awaitable[Any]: ...
    def xread(
        self, streams: Any, count: int | None = ..., block: int | None = ...
    ) -> Awaitable[Any]: ...
    def set(self, name: str, value: str, ex: int | None = ...) -> Awaitable[Any]: ...
    def get(self, name: str) -> Awaitable[Any]: ...
    def exists(self, *names: str) -> Awaitable[Any]: ...
    def expire(self, name: str, time: int) -> Awaitable[Any]: ...


# Long enough for a client to reconnect past a network blip, short enough not to accumulate forever.
_STREAM_TTL_SECONDS = 3600
_STOP_FLAG_TTL_SECONDS = 3600
# XREAD BLOCK timeout per poll; bounds how long a tailer goes without re-checking the stop flag.
_BLOCK_MS = 5000

_END_SENTINEL = "__end__"


def build_redis_client(settings: Settings) -> redis.Redis | None:
    if not settings.REDIS_URL:
        return None
    # Lazy: from_url never touches the network; the first real command does.
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def build_stream_bus(redis_client: redis.Redis | None) -> RedisStreamBus | None:
    return RedisStreamBus(redis_client) if redis_client is not None else None


class RedisStreamBus:
    def __init__(self, redis_client: RedisStreamClient) -> None:
        self._redis = redis_client

    @staticmethod
    def _events_key(stream_id: str) -> str:
        return f"chat:stream:{stream_id}:events"

    @staticmethod
    def _stop_key(stream_id: str) -> str:
        return f"chat:stream:{stream_id}:stop"

    @staticmethod
    def _owner_key(stream_id: str) -> str:
        return f"chat:stream:{stream_id}:owner"

    async def record_owner(self, stream_id: str, user_id: str) -> None:
        """Called before the response returns X-Stream-Id, so no window exists for a resume/stop call to race this write."""
        await self._redis.set(self._owner_key(stream_id), user_id, ex=_STREAM_TTL_SECONDS)

    async def get_owner(self, stream_id: str) -> str | None:
        """None means "no owner on record"; intentionally doesn't fail closed, to avoid a TTL expiry becoming a false rejection."""
        value = await self._redis.get(self._owner_key(stream_id))
        return str(value) if value is not None else None

    async def publish(self, stream_id: str, *, sse_id: str, event: str, data: str) -> None:
        key = self._events_key(stream_id)
        await self._redis.xadd(key, {"id": sse_id, "event": event, "data": data})
        await self._redis.expire(key, _STREAM_TTL_SECONDS)

    async def publish_end(self, stream_id: str) -> None:
        key = self._events_key(stream_id)
        await self._redis.xadd(key, {"id": "", "event": _END_SENTINEL, "data": ""})
        await self._redis.expire(key, _STREAM_TTL_SECONDS)

    async def request_stop(self, stream_id: str) -> bool:
        """Doesn't guarantee prompt stop -- only checked between events; asyncio.Task.cancel() is the same-process complement."""
        exists = bool(await self._redis.exists(self._events_key(stream_id)))
        await self._redis.set(self._stop_key(stream_id), "1", ex=_STOP_FLAG_TTL_SECONDS)
        return exists

    async def is_stop_requested(self, stream_id: str) -> bool:
        return bool(await self._redis.exists(self._stop_key(stream_id)))

    async def replay_and_tail(
        self, stream_id: str, *, last_event_id: str | None
    ) -> AsyncIterator[tuple[str, str, str]]:
        """Yields (sse_id, event_type, data_json): replay from last_event_id (or the start if None), then tail until stopped."""
        key = self._events_key(stream_id)
        start = await self._resolve_start(key, last_event_id)
        if start is None:
            return

        cursor = start
        while True:
            if await self.is_stop_requested(stream_id):
                return
            response = await self._redis.xread({key: cursor}, count=200, block=_BLOCK_MS)
            entries = _flatten_xread_response(response, key)
            if not entries:
                continue
            for redis_id, fields in entries:
                cursor = redis_id
                if fields.get("event") == _END_SENTINEL:
                    return
                yield fields["id"], fields.get("event") or "message", fields["data"]

    async def _resolve_start(self, key: str, last_event_id: str | None) -> str | None:
        if last_event_id is None:
            return "0"

        raw = await self._redis.xrange(key, min="-", max="+")
        entries = _normalize_stream_entries(raw)
        if not entries:
            # Nothing buffered under this stream_id -- the caller treats this as "unknown stream".
            return None

        for redis_id, fields in entries:
            if fields.get("id") == last_event_id:
                return redis_id
        # Last-seen id isn't in our buffer (e.g. predates the TTL window) -- replay everything rather than drop events.
        return "0"


def _normalize_stream_entries(raw: Any) -> list[tuple[str, dict[str, str]]]:
    """Narrows redis-py's bytes | str | None field stubs to plain str, matching decode_responses=True's actual runtime shape."""
    if not raw:
        return []
    entries: list[tuple[str, dict[str, str]]] = []
    for redis_id, fields in raw:
        entries.append((str(redis_id), {str(k): str(v) for k, v in (fields or {}).items()}))
    return entries


def _flatten_xread_response(response: Any, key: str) -> list[tuple[str, dict[str, str]]]:
    """Handles both RESP2 (dict) and RESP3 (list-of-pairs) shapes redis-py's stubs allow for the same call."""
    if not response:
        return []
    if isinstance(response, dict):
        raw_entries = response.get(key, [])
    else:
        raw_entries = next((entries for k, entries in response if k == key), [])
    return _normalize_stream_entries(raw_entries)
