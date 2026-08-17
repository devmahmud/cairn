"""`ChatStreamer` -- translates the chat graph's stream into SSE (BLUEPRINT.md §3.6, §3.7, §8 step 6).

The one place graph events (`agents/chat/agent.py::ChatAgent.astream`, itself
`agents/chat/graph.py`'s `graph.astream(stream_mode=[...])`) become
`modules/chat/sse.py::ChatSSEEvent`s -- the graph itself emits no SSE (§3.1).

**Transaction discipline (§3.3, the "v1 gap"):** no request-scoped session is
held across a turn. `ChatStreamer` is handed the raw `async_sessionmaker`
(not `core.db.engine.get_session`) and opens exactly two short transactions
per turn, both via `_unit_of_work` below:
1. `begin_turn` -- validate the conversation is owned by this user and
   idempotently insert the user's message (`MessageRepository.create_idempotent`,
   reused as-is from `modules/conversations/repository.py` -- same table,
   same dedup rule, no reason for a second implementation). Runs as a FastAPI
   *dependency* (`modules/chat/router.py`), not inside the SSE generator
   itself, specifically so a bad `conversation_id` still comes back as a
   normal `404` -- once the streaming response begins, raising doesn't
   produce an HTTP error status anymore (§3.7).
2. `_persist_reply` -- insert the assistant's final message, after the graph
   run (and the LLM call within it) has fully finished. Neither transaction
   is ever open while `ChatAgent.astream` is being awaited/iterated.

**Two producer shapes, one core generator (`_run_turn`):**
- **Simple mode** (`stream_turn_simple`) -- the producer runs in-request;
  `modules/chat/router.py`'s endpoint yields its `ServerSentEvent`s straight
  into FastAPI's native `EventSourceResponse`.
- **Durable mode** (`run_durable_producer`, `STREAM_DURABLE=true` +
  `REDIS_URL`) -- the same `_run_turn` output is instead published to
  `core/stream/resume.py`'s `RedisStreamBus`, decoupled from the request
  that started it; `GET /chat/stream/{stream_id}` tails it independently.
`durable_enabled` is what `router.py` checks to pick a mode, degrading to
simple mode when Redis isn't configured (§3.7: "not error").
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi.sse import ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.chat.agent import ChatAgent
from agents.chat.nodes.route import VALID_ROUTES
from core.config import Settings, settings
from core.errors.exceptions import NotFoundError
from core.stream.resume import RedisStreamBus
from modules.chat.sse import (
    AgentSwitchEvent,
    ChatSSEEvent,
    Citation,
    DecisionEvent,
    ErrorEvent,
    GuardrailEvent,
    MessageDeltaEvent,
    MessageEndEvent,
    MessageStartEvent,
    SSEEventFormatter,
    ToolResultEvent,
)
from modules.conversations.models import Conversation, Message
from modules.conversations.repository import ConversationRepository, MessageRepository

logger = structlog.get_logger(__name__)

_GENERIC_ERROR_MESSAGE = "Sorry, something went wrong generating a reply. Please try again."

#: Nodes whose `stream_mode="messages"` chunks are safe to surface as
#: `message_delta` text (§3.6's "plain-text node" case, plus `tool`'s own
#: final non-tool-call turn -- see `agents/chat/nodes/tool.py`'s docstring).
#: `rag` deliberately isn't here: it streams via a custom writer instead
#: (`_CUSTOM_WRITER_NODES`), and would otherwise double-emit its text.
_MESSAGES_MODE_NODES = frozenset({"answer", "tool"})

#: Nodes that push text through `get_stream_writer()` instead of relying on
#: LangGraph's auto-streamed model events (§3.6, §3.7).
_CUSTOM_WRITER_NODES = frozenset({"rag"})


@asynccontextmanager
async def _unit_of_work(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One short, explicit transaction -- the same contract as
    `core.db.engine.get_session`, usable outside FastAPI's `Depends` (§3.3)."""
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@dataclass(slots=True)
class TurnContext:
    """What `ChatStreamer.begin_turn` hands off to the actual streaming step.

    `replay` is set when this turn's `idempotency_key` was already used
    (a retried/reconnected `POST /chat`, §3.3): the assistant's reply from
    the original attempt, if the turn had already finished, so a retry never
    re-runs the graph (and never double-fires an LLM call, however
    idempotent the rest of the turn is) -- it just re-plays the same result.
    `None` means either no key was given, or this is genuinely the first
    attempt.
    """

    conversation_id: UUID
    user_id: UUID
    text: str
    message_id: UUID
    replay: Message | None


class ChatStreamer:
    def __init__(
        self,
        *,
        chat_agent: ChatAgent,
        sessionmaker: async_sessionmaker[AsyncSession],
        stream_bus: RedisStreamBus | None = None,
        app_settings: Settings = settings,
    ) -> None:
        self._chat_agent = chat_agent
        self._sessionmaker = sessionmaker
        self._stream_bus = stream_bus
        self._settings = app_settings

    @property
    def durable_enabled(self) -> bool:
        """§3.7: durable mode needs both the flag and a configured Redis bus.

        `self._stream_bus` is already `None` whenever `REDIS_URL` is unset
        (`core/stream/resume.py::build_stream_bus`) -- so this alone
        implements "if `REDIS_URL` is unset, fall back to simple mode, not
        error."
        """
        return self._settings.STREAM_DURABLE and self._stream_bus is not None

    @property
    def stream_bus(self) -> RedisStreamBus | None:
        return self._stream_bus

    # --- Transaction #1: validate + idempotent user-message insert ---------

    async def begin_turn(
        self, *, conversation_id: UUID, user_id: UUID, text: str, idempotency_key: str | None
    ) -> TurnContext:
        async with _unit_of_work(self._sessionmaker) as session:
            conversations = ConversationRepository(session)
            messages = MessageRepository(session)

            conversation: Conversation | None = await conversations.get_owned(
                conversation_id, user_id=user_id
            )
            if conversation is None:
                raise NotFoundError(f"Conversation {conversation_id} not found.")

            user_message = Message(
                conversation_id=conversation_id,
                role="user",
                content=text,
                # Explicit `[]`, not omitted: a transient (never-flushed)
                # `Message` leaves these Python-`None` until the DB's
                # `server_default` applies at flush -- fine for `add()`, but
                # `create_idempotent`'s manual `INSERT ... VALUES` (below)
                # reads these attributes *before* any flush, so a `None`
                # here would be sent as a literal `NULL`. `Message.artifacts`/
                # `.citations` are JSONB, not `none_as_null`, so SQLAlchemy
                # serializes that `None` as the JSON literal `null` -- valid
                # against the column's `NOT NULL` constraint (it isn't SQL
                # NULL), but not a `list`, so `MessageRead` rejects it on
                # the next read. `modules/conversations/service.py::add_message`
                # never hits this because `MessageCreate`'s Pydantic defaults
                # already fill in `[]` before it ever builds a `Message`.
                artifacts=[],
                citations=[],
                idempotency_key=idempotency_key,
            )
            _user_message, created = await messages.create_idempotent(user_message)

            replay: Message | None = None
            if not created:
                replay = await self._existing_reply(messages, conversation_id)

        return TurnContext(
            conversation_id=conversation_id,
            user_id=user_id,
            text=text,
            message_id=uuid4(),
            replay=replay,
        )

    @staticmethod
    async def _existing_reply(messages: MessageRepository, conversation_id: UUID) -> Message | None:
        page = await messages.list_for_conversation(conversation_id, limit=1)
        if not page.items:
            return None
        candidate = page.items[0]
        return candidate if candidate.role == "assistant" else None

    # --- Simple mode ---------------------------------------------------------

    async def stream_turn_simple(self, turn: TurnContext) -> AsyncIterator[ServerSentEvent]:
        formatter = SSEEventFormatter()
        async for event in self._run_turn(turn, stream_id=None):
            yield formatter.format(event)

    # --- Durable mode ----------------------------------------------------------

    async def run_durable_producer(self, *, stream_id: str, turn: TurnContext) -> None:
        """Run the turn to completion, publishing every event to Redis.

        Decoupled from the request that started it (`modules/chat/router.py`
        runs this as a background `asyncio.Task`, not awaited inline) -- it
        keeps running (and keeps writing durable frames a reconnecting client
        can replay) even if the original HTTP request disconnects. Always
        publishes the end-of-stream sentinel, however the turn finished
        (success, mid-turn error, or a `/stop`-requested/task-cancelled
        early exit), so every tailer reliably stops waiting.
        """
        assert self._stream_bus is not None
        formatter = SSEEventFormatter()
        try:
            async for event in self._run_turn(turn, stream_id=stream_id):
                if await self._stream_bus.is_stop_requested(stream_id):
                    break
                sse_id, event_type, data_json = formatter.format_raw(event)
                await self._stream_bus.publish(
                    stream_id, sse_id=sse_id, event=event_type, data=data_json
                )
        except Exception:
            logger.exception("chat_stream.durable_producer_failed", stream_id=stream_id)
        finally:
            await self._stream_bus.publish_end(stream_id)

    async def tail_durable(
        self, *, stream_id: str, last_event_id: str | None
    ) -> AsyncIterator[ServerSentEvent]:
        assert self._stream_bus is not None
        async for sse_id, event_type, data_json in self._stream_bus.replay_and_tail(
            stream_id, last_event_id=last_event_id
        ):
            yield ServerSentEvent(id=sse_id, event=event_type, raw_data=data_json)

    # --- Shared core: graph -> domain SSE events, then persist --------------

    async def _run_turn(
        self, turn: TurnContext, *, stream_id: str | None
    ) -> AsyncIterator[ChatSSEEvent]:
        if turn.replay is not None:
            for event in _replay_events(turn.replay, message_id=turn.message_id):
                yield event
            return

        translator = _EventTranslator(
            conversation_id=turn.conversation_id, message_id=turn.message_id, stream_id=stream_id
        )
        final_state: dict[str, Any] = {}
        try:
            async for mode, payload in self._chat_agent.astream(
                conversation_id=turn.conversation_id, user_id=turn.user_id, text=turn.text
            ):
                if mode == "timeout":
                    if isinstance(payload, Mapping):
                        final_state.update(payload)
                    yield ErrorEvent(
                        code="turn_budget_exceeded",
                        message=str(final_state.get("answer") or _GENERIC_ERROR_MESSAGE),
                    )
                    break

                for event in translator.handle(mode, payload):
                    yield event

                if mode == "updates" and isinstance(payload, Mapping):
                    for update in payload.values():
                        if update:
                            final_state.update(update)
        except Exception:
            logger.exception("chat_stream.turn_failed", conversation_id=str(turn.conversation_id))
            yield ErrorEvent(code="stream_failed", message=_GENERIC_ERROR_MESSAGE)
            return

        try:
            await self._persist_reply(turn, final_state)
        except Exception:
            # The client already has the full reply via SSE (every event
            # above this point already streamed) -- a persistence failure
            # here is a durability problem to alert on (structlog), not one
            # that should retroactively surface as a stream error after
            # `message_end` already went out.
            logger.exception(
                "chat_stream.persist_reply_failed", conversation_id=str(turn.conversation_id)
            )

    # --- Transaction #2: persist the final assistant message -----------------

    async def _persist_reply(self, turn: TurnContext, final_state: dict[str, Any]) -> None:
        answer_text = str(final_state.get("answer") or "")
        citations_raw = final_state.get("citations") or []
        async with _unit_of_work(self._sessionmaker) as session:
            messages = MessageRepository(session)
            await messages.add(
                Message(
                    id=turn.message_id,
                    conversation_id=turn.conversation_id,
                    role="assistant",
                    content=answer_text,
                    artifacts=[],
                    citations=citations_raw,
                )
            )


def _replay_events(message: Message, *, message_id: UUID) -> list[ChatSSEEvent]:
    """The SSE sequence for a retried turn whose reply already exists (§3.3).

    Uses the *original* reply's own id (not this retry's `message_id`) --
    the client already has (or will fetch via REST) that message row; this
    just replays its content as a completed stream instead of re-running
    the graph.
    """
    events: list[ChatSSEEvent] = [
        MessageStartEvent(message_id=str(message.id), conversation_id=str(message.conversation_id))
    ]
    if message.content:
        events.append(MessageDeltaEvent(message_id=str(message.id), text=message.content))
    events.append(
        MessageEndEvent(
            message_id=str(message.id),
            citations=[Citation(**c) for c in (message.citations or [])],
        )
    )
    return events


#: Background producer tasks for durable-mode turns, keyed by `stream_id`
#: (§3.7). Process-local by design -- `chat_streamer` is a DI `Factory`
#: (§3.4), so a per-instance registry wouldn't be shared between the request
#: that spawns a producer and a later request that stops it; module-level
#: state is what makes both see the same task. This is the immediate-effect,
#: same-process half of stopping a stream -- `RedisStreamBus.request_stop`
#: (`core/stream/resume.py`) is the cross-process-safe, best-effort half a
#: tailer honors regardless of which process the producer is actually on.
_DURABLE_PRODUCER_TASKS: dict[str, asyncio.Task[None]] = {}


def spawn_durable_producer(streamer: ChatStreamer, *, stream_id: str, turn: TurnContext) -> None:
    task = asyncio.create_task(streamer.run_durable_producer(stream_id=stream_id, turn=turn))
    _DURABLE_PRODUCER_TASKS[stream_id] = task
    task.add_done_callback(lambda _task: _DURABLE_PRODUCER_TASKS.pop(stream_id, None))


def cancel_durable_producer(stream_id: str) -> bool:
    """Best-effort, same-process cancellation; returns whether it found one to cancel."""
    task = _DURABLE_PRODUCER_TASKS.get(stream_id)
    if task is not None and not task.done():
        task.cancel()
        return True
    return False


def _content_to_text(content: Any) -> str:
    """Normalize a `BaseMessageChunk.content` (str, or a list of content
    blocks) to `str` -- the same normalization `agents/chat/nodes/_util.py`
    applies, kept as its own copy here since that module is private to
    `agents/chat/nodes/` (see its own docstring)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "".join(parts)
    return str(content) if content is not None else ""


class _EventTranslator:
    """Turns one turn's `(stream_mode, payload)` tuples into `ChatSSEEvent`s.

    Stateful per turn (tracks which branch node is currently "the" message
    being produced, and whether it's already streamed any delta text) --
    always construct a fresh instance per `_run_turn` call.
    """

    def __init__(self, *, conversation_id: UUID, message_id: UUID, stream_id: str | None) -> None:
        self._conversation_id = str(conversation_id)
        self._message_id = str(message_id)
        self._stream_id = stream_id
        self._current_node: str | None = None
        self._delta_emitted = False

    def handle(self, mode: str, payload: Any) -> list[ChatSSEEvent]:
        if mode == "updates":
            return self._handle_updates(payload)
        if mode == "messages":
            return self._handle_messages(payload)
        if mode == "custom":
            return self._handle_custom(payload)
        return []

    # -- "updates": one node's partial state update as it completes ---------

    def _handle_updates(self, payload: Any) -> list[ChatSSEEvent]:
        if not isinstance(payload, Mapping):
            return []
        events: list[ChatSSEEvent] = []
        for node_name, update in payload.items():
            events.extend(self._handle_node_update(str(node_name), update or {}))
        return events

    def _handle_node_update(self, node_name: str, update: Mapping[str, Any]) -> list[ChatSSEEvent]:
        if node_name == "classify":
            if "intent" not in update:
                return []
            return [
                DecisionEvent(
                    intent=str(update.get("intent") or "unclear"),
                    confidence=float(update.get("confidence") or 0.0),
                )
            ]

        if node_name == "route":
            route = update.get("route")
            if not isinstance(route, str) or route not in VALID_ROUTES:
                return []
            self._current_node = route
            self._delta_emitted = False
            return [
                AgentSwitchEvent(agent=route),
                MessageStartEvent(
                    message_id=self._message_id,
                    conversation_id=self._conversation_id,
                    stream_id=self._stream_id,
                ),
            ]

        if node_name not in VALID_ROUTES or node_name != self._current_node:
            # `input_rail`/`output_rail` (no-ops today, §8 step 7), or an
            # update for a node that isn't this turn's active branch.
            return []

        return self._handle_branch_completion(node_name, update)

    def _handle_branch_completion(
        self, node_name: str, update: Mapping[str, Any]
    ) -> list[ChatSSEEvent]:
        events: list[ChatSSEEvent] = []

        if node_name == "guardrail":
            events.append(GuardrailEvent(action="clarify", message=str(update.get("answer") or "")))

        error = update.get("error")
        if error:
            events.append(
                ErrorEvent(
                    code=str(error), message=str(update.get("answer") or _GENERIC_ERROR_MESSAGE)
                )
            )

        answer = update.get("answer")
        if not self._delta_emitted and answer:
            events.append(MessageDeltaEvent(message_id=self._message_id, text=str(answer)))

        citations_raw = update.get("citations") or []
        events.append(
            MessageEndEvent(
                message_id=self._message_id,
                citations=[Citation(**c) for c in citations_raw],
            )
        )

        self._current_node = None
        self._delta_emitted = False
        return events

    # -- "messages": auto-streamed model output (§3.6's "plain-text" case) --

    def _handle_messages(self, payload: Any) -> list[ChatSSEEvent]:
        if self._current_node is None or self._current_node not in _MESSAGES_MODE_NODES:
            return []
        try:
            chunk, metadata = payload
        except (TypeError, ValueError):
            return []
        node = metadata.get("langgraph_node") if isinstance(metadata, Mapping) else None
        if node != self._current_node:
            return []

        text = _content_to_text(getattr(chunk, "content", None))
        if not text:
            return []
        self._delta_emitted = True
        return [MessageDeltaEvent(message_id=self._message_id, text=text)]

    # -- "custom": whatever a node pushed via `get_stream_writer()` ---------

    def _handle_custom(self, payload: Any) -> list[ChatSSEEvent]:
        if not isinstance(payload, Mapping):
            return []
        node = payload.get("node")
        if node != self._current_node:
            return []

        if node in _CUSTOM_WRITER_NODES and payload.get("type") is None:
            text = payload.get("text")
            if isinstance(text, str) and text:
                self._delta_emitted = True
                return [MessageDeltaEvent(message_id=self._message_id, text=text)]
            return []

        if payload.get("type") == "tool_result":
            tool_name, result = payload.get("tool_name"), payload.get("result")
            if isinstance(tool_name, str) and isinstance(result, str):
                return [ToolResultEvent(tool_name=tool_name, result=result)]

        return []
