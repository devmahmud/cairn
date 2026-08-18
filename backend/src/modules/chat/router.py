"""HTTP surface for chat streaming; every check below runs as a dependency, never inside a generator body -- raising after an SSE response commits its 200 breaks the stream instead of returning a clean HTTP error."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from core.di.container import container as di_container
from core.errors.exceptions import NotFoundError
from core.limits.rate_limit import chat_rate_limit
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
    # The one DI-container-wired dependency here; everything else in this module uses plain FastAPI Depends.
    return di_container.chat_streamer()


StreamerDep = Annotated[ChatStreamer, Depends(get_chat_streamer)]
UserIdDep = Annotated[UUID, Depends(get_current_user_id)]


@dataclass(slots=True)
class _TurnHandle:
    """stream_id is None means simple mode; otherwise its producer is already spawned by the time this returns."""

    turn: TurnContext
    stream_id: str | None


@chat_rate_limit  # On this dependency, not start_chat_turn: slowapi awaits its wrapped callable, which breaks FastAPI's async-generator SSE detection.
async def _start_chat_turn(
    request: Request,
    payload: ChatTurnRequest,
    streamer: StreamerDep,
    user_id: UserIdDep,
    response: Response,
) -> _TurnHandle:
    """X-Stream-Id is set here, not from inside the generator body: FastAPI's SSE producer merges Response headers before the generator's first line runs, so a header set there isn't reliably visible to the client."""
    turn = await streamer.begin_turn(
        conversation_id=payload.conversation_id,
        user_id=user_id,
        text=payload.text,
        idempotency_key=payload.idempotency_key,
    )
    if not streamer.durable_enabled:
        return _TurnHandle(turn=turn, stream_id=None)

    stream_id = uuid4().hex
    # Before the response goes out and before the producer spawns, so no client-visible stream_id can lack an owner record.
    await streamer.record_stream_owner(stream_id=stream_id, user_id=user_id)
    response.headers["X-Stream-Id"] = stream_id
    spawn_durable_producer(streamer, stream_id=stream_id, turn=turn)
    return _TurnHandle(turn=turn, stream_id=stream_id)


TurnHandleDep = Annotated[_TurnHandle, Depends(_start_chat_turn)]


async def _require_durable_streamer(streamer: StreamerDep) -> ChatStreamer:
    """404 if durable mode isn't enabled -- a dependency so it fails before the SSE response commits its 200."""
    if not streamer.durable_enabled:
        raise NotFoundError("Durable streaming is not enabled on this deployment.")
    return streamer


DurableStreamerDep = Annotated[ChatStreamer, Depends(_require_durable_streamer)]


async def _ensure_stream_owned(streamer: ChatStreamer, *, stream_id: str, user_id: UUID) -> None:
    """404, not 403 -- doesn't distinguish "not yours" from "doesn't exist", so a caller can't fish for which stream_ids are real."""
    if not await streamer.is_stream_owner(stream_id=stream_id, user_id=user_id):
        raise NotFoundError(f"Stream {stream_id!r} not found.")


async def _ensure_stream_owned_dep(
    stream_id: str, streamer: DurableStreamerDep, user_id: UserIdDep
) -> None:
    """Dependency wrapper for resume_chat_stream; stop_chat_stream isn't streaming, so it calls _ensure_stream_owned directly."""
    await _ensure_stream_owned(streamer, stream_id=stream_id, user_id=user_id)


# SSE endpoints don't use response_model; this is what makes /openapi.json document their body shape via register_sse_schema.
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
    _owned: Annotated[None, Depends(_ensure_stream_owned_dep)],
    last_event_id: Annotated[str | None, Query()] = None,
) -> AsyncIterator[ServerSentEvent]:
    async for event in streamer.tail_durable(stream_id=stream_id, last_event_id=last_event_id):
        yield event


@router.post("/stream/{stream_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_chat_stream(
    stream_id: str, streamer: DurableStreamerDep, user_id: UserIdDep
) -> None:
    assert streamer.stream_bus is not None
    await _ensure_stream_owned(streamer, stream_id=stream_id, user_id=user_id)

    stream_known = await streamer.stream_bus.request_stop(stream_id)
    cancelled_locally = cancel_durable_producer(stream_id)
    if not stream_known and not cancelled_locally:
        raise NotFoundError(f"Stream {stream_id!r} not found.")
