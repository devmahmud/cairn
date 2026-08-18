"""Unit tests for `core.stream.resume.RedisStreamBus` (BLUEPRINT.md §3.7, §8 step 6).

Runs against `_FakeRedisStreams` -- a tiny in-memory double implementing
just the `RedisStreamClient` Protocol's methods with real Redis Streams
semantics (monotonic `ms-seq` ids, `XREAD`'s "strictly after" cursor
semantics) -- no real Redis involved.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.config import Settings
from core.stream.resume import RedisStreamBus, build_redis_client, build_stream_bus


def _parse_id(entry_id: str) -> tuple[int, int]:
    if "-" in entry_id:
        ms, seq = entry_id.split("-", 1)
        return int(ms), int(seq)
    return int(entry_id), 0


class _FakeRedisStreams:
    """Just enough of `redis.asyncio.Redis`'s stream/key API to exercise
    `RedisStreamBus` -- non-blocking (`xread` returns immediately with
    whatever's already there), which is fine since every test here publishes
    everything it wants tailed *before* starting the tail."""

    def __init__(self) -> None:
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._kv: dict[str, str] = {}
        self._counter = 0
        self.expire_calls: list[tuple[str, int]] = []

    async def xadd(self, name: str, fields: dict[str, str]) -> str:
        self._counter += 1
        entry_id = f"{self._counter}-0"
        self._streams.setdefault(name, []).append((entry_id, dict(fields)))
        return entry_id

    async def xrange(
        self, name: str, min: str = "-", max: str = "+", count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        return list(self._streams.get(name, []))

    async def xread(
        self, streams: dict[str, str], count: int | None = None, block: int | None = None
    ) -> dict[str, list[tuple[str, dict[str, str]]]]:
        ((name, after_id),) = streams.items()
        after = _parse_id(after_id)
        entries = [e for e in self._streams.get(name, []) if _parse_id(e[0]) > after]
        return {name: entries} if entries else {}

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        self._kv[name] = value
        return True

    async def get(self, name: str) -> str | None:
        return self._kv.get(name)

    async def exists(self, *names: str) -> int:
        return sum(1 for n in names if n in self._streams or n in self._kv)

    async def expire(self, name: str, time: int) -> bool:
        self.expire_calls.append((name, time))
        return name in self._streams or name in self._kv


def _bus() -> tuple[RedisStreamBus, _FakeRedisStreams]:
    fake = _FakeRedisStreams()
    return RedisStreamBus(fake), fake


async def _collect(agen: Any) -> list[tuple[str, str, str]]:
    return [item async for item in agen]


async def test_replay_and_tail_from_start_yields_everything_then_stops_at_end() -> None:
    bus, _fake = _bus()
    await bus.publish("s1", sse_id="1", event="message_delta", data='{"a":1}')
    await bus.publish("s1", sse_id="2", event="message_end", data="{}")
    await bus.publish_end("s1")

    events = await _collect(bus.replay_and_tail("s1", last_event_id=None))

    assert events == [
        ("1", "message_delta", '{"a":1}'),
        ("2", "message_end", "{}"),
    ]


async def test_replay_and_tail_resumes_strictly_after_last_event_id() -> None:
    bus, _fake = _bus()
    await bus.publish("s1", sse_id="1", event="message_delta", data="a")
    await bus.publish("s1", sse_id="2", event="message_delta", data="b")
    await bus.publish("s1", sse_id="3", event="message_delta", data="c")
    await bus.publish_end("s1")

    events = await _collect(bus.replay_and_tail("s1", last_event_id="1"))

    assert [e[0] for e in events] == ["2", "3"]


async def test_replay_and_tail_falls_back_to_full_replay_for_an_unknown_last_event_id() -> None:
    bus, _fake = _bus()
    await bus.publish("s1", sse_id="1", event="message_delta", data="a")
    await bus.publish("s1", sse_id="2", event="message_delta", data="b")
    await bus.publish_end("s1")

    # The client's `Last-Event-ID` predates this stream's buffer window --
    # replay everything still held rather than silently dropping events.
    events = await _collect(bus.replay_and_tail("s1", last_event_id="999"))

    assert [e[0] for e in events] == ["1", "2"]


async def test_replay_and_tail_yields_nothing_for_a_completely_unknown_stream() -> None:
    bus, _fake = _bus()

    events = await _collect(bus.replay_and_tail("never-published", last_event_id="1"))

    assert events == []


async def test_stop_request_halts_tailing_before_further_buffered_events() -> None:
    bus, _fake = _bus()
    await bus.publish("s1", sse_id="1", event="message_delta", data="a")

    gen = bus.replay_and_tail("s1", last_event_id=None)
    first = await gen.__anext__()
    assert first == ("1", "message_delta", "a")

    # A second event lands, but so does a stop request -- the tailer's next
    # loop iteration checks the flag *before* reading it.
    await bus.publish("s1", sse_id="2", event="message_delta", data="b")
    await bus.request_stop("s1")

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


async def test_request_stop_reports_whether_the_stream_was_known() -> None:
    bus, _fake = _bus()

    assert await bus.request_stop("unknown-stream") is False

    await bus.publish("known-stream", sse_id="1", event="x", data="{}")
    assert await bus.request_stop("known-stream") is True


async def test_is_stop_requested_reflects_request_stop() -> None:
    bus, _fake = _bus()
    await bus.publish("s1", sse_id="1", event="x", data="{}")

    assert await bus.is_stop_requested("s1") is False
    await bus.request_stop("s1")
    assert await bus.is_stop_requested("s1") is True


async def test_publish_and_publish_end_refresh_the_stream_ttl() -> None:
    bus, fake = _bus()

    await bus.publish("s1", sse_id="1", event="message_delta", data="a")
    await bus.publish_end("s1")

    assert fake.expire_calls == [
        ("chat:stream:s1:events", 3600),
        ("chat:stream:s1:events", 3600),
    ]


def test_build_redis_client_is_none_when_redis_url_is_unset() -> None:
    assert build_redis_client(Settings(REDIS_URL="")) is None


def test_build_stream_bus_is_none_without_a_client() -> None:
    assert build_stream_bus(None) is None


def test_build_stream_bus_wraps_a_real_client() -> None:
    fake = _FakeRedisStreams()
    bus = build_stream_bus(fake)  # type: ignore[arg-type]
    assert isinstance(bus, RedisStreamBus)
