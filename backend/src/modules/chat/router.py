"""HTTP surface for the chat streaming endpoint (BLUEPRINT.md §3.7, §8 step 6).

Three endpoints, mirroring §3.7's contract:
- `POST /chat` -- starts a turn; streams via FastAPI's native
  `EventSourceResponse` (§1: heartbeat/disconnect/`Last-Event-ID` handling
  built in, no `sse-starlette`). In durable mode, also spawns a decoupled
  background producer and embeds/returns its `stream_id` (`X-Stream-Id`
  header, and on the first event via `MessageStartEvent.stream_id`).
- `GET /chat/stream/{stream_id}` -- replay-from-`last_event_id` then tail;
  durable mode only.
- `POST /chat/stream/{stream_id}/stop` -- true terminate (vs. a network
  drop, which a durable producer keeps running through); durable mode only.

Turn validation (`begin_turn`) runs as a *dependency*, before the SSE
response begins -- see `chat_stream.py`'s module docstring for why a bad
`conversation_id` needs to fail there, not inside the generator, to still
come back as a normal `404`. Protected by the same `get_current_user_id`
abstraction the `conversations` module depends on (§3.9); real auth (§8 step
7) upgrades that one function for every router at once, this one included --
this module never hand-rolls its own auth check.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from core.di.container import container as di_container
from core.errors.exceptions import NotFoundError
from core.security.current_user import get_current_user_id
from modules.chat.chat_stream import (
    ChatStreamer,
    TurnContext,
    cancel_durable_producer,
    spawn_durable_producer,
)
from modules.chat.schemas import ChatTurnRequest

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_streamer() -> ChatStreamer:
    # `chat_streamer` is the one DI-container-wired dependency this module
    # has (§3.4: the container is reserved for the singleton agent graph and
    # its collaborators) -- everything else here is plain FastAPI `Depends`,
    # same split the `conversations` module makes.
    return di_container.chat_streamer()


StreamerDep = Annotated[ChatStreamer, Depends(get_chat_streamer)]
UserIdDep = Annotated[UUID, Depends(get_current_user_id)]


@dataclass(slots=True)
class _TurnHandle:
    """What `_start_chat_turn` hands the endpoint: the validated turn, and
    (durable mode only) the `stream_id` its producer was already spawned
    under. `stream_id is None` means simple mode."""

    turn: TurnContext
    stream_id: str | None


async def _start_chat_turn(
    payload: ChatTurnRequest, streamer: StreamerDep, user_id: UserIdDep, response: Response
) -> _TurnHandle:
    """Validates the turn *and* (durable mode) spawns its producer + sets
    `X-Stream-Id` -- all as a dependency, not inside `start_chat_turn`'s
    generator body.

    Two independent reasons this can't live in the endpoint body, not just
    one: `begin_turn`'s own reason (a bad `conversation_id` needs to fail as
    a normal `404` -- `chat_stream.py`'s module docstring, `resume_chat_stream`'s
    `_require_durable_streamer` above), *and* a second, narrower one specific
    to `X-Stream-Id` -- FastAPI's native SSE producer merges the `Response`
    dependency's headers into the actual `StreamingResponse` right after
    entering its internal producer context manager, which races ahead of
    the generator body's *own* first line of code (scheduled via
    `anyio`'s `start_soon`, not run inline). A header set from inside the
    generator is therefore not reliably visible on the response by the time
    the client sees it; setting it here, before the generator/response
    exist at all, is.
    """
    turn = await streamer.begin_turn(
        conversation_id=payload.conversation_id,
        user_id=user_id,
        text=payload.text,
        idempotency_key=payload.idempotency_key,
    )
    if not streamer.durable_enabled:
        return _TurnHandle(turn=turn, stream_id=None)

    stream_id = uuid4().hex
    response.headers["X-Stream-Id"] = stream_id
    spawn_durable_producer(streamer, stream_id=stream_id, turn=turn)
    return _TurnHandle(turn=turn, stream_id=stream_id)


TurnHandleDep = Annotated[_TurnHandle, Depends(_start_chat_turn)]


async def _require_durable_streamer(streamer: StreamerDep) -> ChatStreamer:
    """`404` if durable mode isn't enabled -- a dependency, not an in-body
    check, for the same reason `_begin_turn` is: `resume_chat_stream` is a
    generator-based `EventSourceResponse` endpoint, and raising from *inside*
    one doesn't produce a clean HTTP status (§3.7, `chat_stream.py`'s module
    docstring) -- by the time the generator body starts running, FastAPI's
    native SSE machinery has already committed a `200` and started
    streaming. Running this check as a dependency means it fails before any
    of that happens.
    """
    if not streamer.durable_enabled:
        raise NotFoundError("Durable streaming is not enabled on this deployment.")
    return streamer


DurableStreamerDep = Annotated[ChatStreamer, Depends(_require_durable_streamer)]

#: `openapi_extra`-free, plain `responses=` override (§3.7): SSE endpoints
#: return `ServerSentEvent`s, not a `response_model`, so this is the only way
#: `/openapi.json` documents their body shape -- `modules/chat/sse.py`'s
#: `register_sse_schema` (called from `main.py`) is what makes the
#: `$ref` below resolve to something real.
_SSE_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {
        "description": "Server-sent stream of chat turn events.",
        "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/ChatSSEEvent"}}},
    },
}


@router.post("", response_class=EventSourceResponse, responses=_SSE_RESPONSES)
async def start_chat_turn(
    handle: TurnHandleDep, streamer: StreamerDep
) -> AsyncIterator[ServerSentEvent]:
    if handle.stream_id is not None:
        async for event in streamer.tail_durable(stream_id=handle.stream_id, last_event_id=None):
            yield event
        return

    async for event in streamer.stream_turn_simple(handle.turn):
        yield event


@router.get("/stream/{stream_id}", response_class=EventSourceResponse, responses=_SSE_RESPONSES)
async def resume_chat_stream(
    stream_id: str,
    streamer: DurableStreamerDep,
    _user_id: UserIdDep,
    last_event_id: Annotated[str | None, Query()] = None,
) -> AsyncIterator[ServerSentEvent]:
    async for event in streamer.tail_durable(stream_id=stream_id, last_event_id=last_event_id):
        yield event


@router.post("/stream/{stream_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_chat_stream(
    stream_id: str, streamer: DurableStreamerDep, _user_id: UserIdDep
) -> None:
    assert streamer.stream_bus is not None

    stream_known = await streamer.stream_bus.request_stop(stream_id)
    cancelled_locally = cancel_durable_producer(stream_id)
    if not stream_known and not cancelled_locally:
        raise NotFoundError(f"Stream {stream_id!r} not found.")
