"""Redis-backed durable stream bus (BLUEPRINT.md §3.7, §8 step 6).

Backs `STREAM_DURABLE=true` mode: `modules/chat/chat_stream.py`'s producer
writes `id:`-stamped frames here, decoupled from any one HTTP request, keyed
by a server-generated `stream_id`; `GET /chat/stream/{stream_id}` tails them.
A turn's frames are a Redis Stream (`XADD`/`XRANGE`/`XREAD`) -- its native
ID ordering does the replay-then-tail job for free, and a client's
`Last-Event-ID` (our own monotonic `id:`, stamped by
`modules/chat/sse.py::SSEEventFormatter`, *not* Redis' own `ms-seq` id) is
resolved to a Redis-native starting point with one `XRANGE` scan before the
blocking tail begins.

`build_redis_client`/`build_stream_bus` return `None` when `REDIS_URL` is
unset -- offline-first (design principle #4): constructing the DI
container's providers never requires Redis to be running, and
`ChatStreamer.durable_enabled` degrades to simple-mode streaming rather than
erroring (§3.7: "If REDIS_URL is unset, this mode is unavailable ... not
error").
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Any, Protocol

import redis.asyncio as redis
import structlog

from core.config import Settings

logger = structlog.get_logger(__name__)


class RedisStreamClient(Protocol):
    """The slice of `redis.asyncio.Redis` `RedisStreamBus` actually needs.

    A `Protocol`, not a hard dependency on `redis.asyncio.Redis` -- same
    reasoning as `core/prompts/engine.py`'s `LangfusePromptClient`: keeps
    this class trivially testable against an in-memory fake with no real
    Redis involved, and decouples it from the concrete client's (much
    larger, loosely-typed) surface.
    """

    # Loosely typed on purpose: redis-py's own stubs accept `bytes | str |
    # memoryview` (and use invariant `dict[...]` params) throughout, which
    # no reasonably-narrow signature here stays structurally compatible
    # with -- this Protocol exists to pin down *which methods* `RedisStreamBus`
    # needs, not to re-derive redis-py's full parameter typing. Plain
    # `def ... -> Awaitable[Any]`, not `async def`, for the same reason on
    # the return side (an `async def` here would require the implementer's
    # call to resolve to exactly `Coroutine[Any, Any, Any]`, which
    # `Awaitable[bool]`-declared real methods don't).
    def xadd(self, name: str, fields: Any) -> Awaitable[Any]: ...
    def xrange(
        self, name: str, min: str = ..., max: str = ..., count: int | None = ...
    ) -> Awaitable[Any]: ...
    def xread(
        self, streams: Any, count: int | None = ..., block: int | None = ...
    ) -> Awaitable[Any]: ...
    def set(self, name: str, value: str, ex: int | None = ...) -> Awaitable[Any]: ...
    def exists(self, *names: str) -> Awaitable[Any]: ...
    def expire(self, name: str, time: int) -> Awaitable[Any]: ...


#: How long a turn's Redis Stream (and its stop flag) survive after the last
#: write -- long enough for a client to reconnect and resume well past any
#: realistic network blip, short enough not to accumulate forever.
_STREAM_TTL_SECONDS = 3600
_STOP_FLAG_TTL_SECONDS = 3600
#: `XREAD BLOCK` timeout per poll (ms) -- bounds how long a tailer can go
#: without re-checking the stop flag (`request_stop`) or noticing the
#: producer already finished (`publish_end`'s sentinel).
_BLOCK_MS = 5000

#: Sentinel `event:` value marking "the producer is done" (success, error,
#: or stopped) -- written by `publish_end`, recognized by `replay_and_tail`.
_END_SENTINEL = "__end__"


def build_redis_client(settings: Settings) -> redis.Redis | None:
    if not settings.REDIS_URL:
        return None
    # Lazy connection pool -- `from_url` itself never touches the network
    # (offline-first); the first actual command does.
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

    async def publish(self, stream_id: str, *, sse_id: str, event: str, data: str) -> None:
        key = self._events_key(stream_id)
        await self._redis.xadd(key, {"id": sse_id, "event": event, "data": data})
        await self._redis.expire(key, _STREAM_TTL_SECONDS)

    async def publish_end(self, stream_id: str) -> None:
        key = self._events_key(stream_id)
        await self._redis.xadd(key, {"id": "", "event": _END_SENTINEL, "data": ""})
        await self._redis.expire(key, _STREAM_TTL_SECONDS)

    async def request_stop(self, stream_id: str) -> bool:
        """Ask the producer to stop; returns whether the stream is known at all.

        `True` doesn't guarantee the producer *will* stop promptly -- it only
        checks between events (`replay_and_tail`'s own poll loop is the other
        half: a tailer that sees the stop flag also stops relaying). A
        same-process `asyncio.Task.cancel()` (the router's own registry,
        `modules/chat/chat_stream.py`) is the immediate-effect complement to
        this Redis-backed, cross-process-safe signal.
        """
        exists = bool(await self._redis.exists(self._events_key(stream_id)))
        await self._redis.set(self._stop_key(stream_id), "1", ex=_STOP_FLAG_TTL_SECONDS)
        return exists

    async def is_stop_requested(self, stream_id: str) -> bool:
        return bool(await self._redis.exists(self._stop_key(stream_id)))

    async def replay_and_tail(
        self, stream_id: str, *, last_event_id: str | None
    ) -> AsyncIterator[tuple[str, str, str]]:
        """Yield `(sse_id, event_type, data_json)` triples: replay, then tail.

        `last_event_id=None` replays from the very start (a fresh
        `POST /chat` in durable mode, tailing its own just-started
        producer). A non-`None` value is the client's `Last-Event-ID` on
        reconnect (`GET /chat/stream/{stream_id}?last_event_id=...`) --
        resolved to a Redis-native id via one `XRANGE` scan so the
        `XREAD`-based tail below only returns entries strictly after it.
        Returns (stops iterating) once the `publish_end` sentinel is seen or
        a stop is requested.
        """
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
            # Nothing buffered under this `stream_id` at all -- the caller
            # (the `GET` resume endpoint) treats this as "unknown stream".
            return None

        for redis_id, fields in entries:
            if fields.get("id") == last_event_id:
                return redis_id
        # The client's last-seen id isn't in our buffer (e.g. it predates
        # this stream's TTL window) -- replay everything we still have
        # rather than silently dropping events.
        return "0"


def _normalize_stream_entries(raw: Any) -> list[tuple[str, dict[str, str]]]:
    """`XRANGE`'s `list[(id, fields)]`, normalized to plain `str`s.

    `decode_responses=True` (`build_redis_client`) already gives `str`s at
    runtime; redis-py's own stubs still type every field as `bytes | str |
    None` (RESP2/RESP3, decoded/undecoded -- one set of stubs covers every
    client configuration), so this is where that gets narrowed down to what
    this module actually works with.
    """
    if not raw:
        return []
    entries: list[tuple[str, dict[str, str]]] = []
    for redis_id, fields in raw:
        entries.append((str(redis_id), {str(k): str(v) for k, v in (fields or {}).items()}))
    return entries


def _flatten_xread_response(response: Any, key: str) -> list[tuple[str, dict[str, str]]]:
    """`XREAD`'s per-key response, flattened to the same shape `XRANGE` gives.

    redis-py's stubs allow two shapes for the same call depending on RESP
    protocol version: `dict[key, entries]` (RESP2) or `[[key, entries], ...]`
    (RESP3) -- both are handled here so this module doesn't care which the
    connected server/client negotiated.
    """
    if not response:
        return []
    if isinstance(response, dict):
        raw_entries = response.get(key, [])
    else:
        raw_entries = next((entries for k, entries in response if k == key), [])
    return _normalize_stream_entries(raw_entries)
