"""Translates the chat graph's stream into SSE; two short transactions per turn, no session held across the LLM call."""

from __future__ import annotations

import asyncio
import contextlib
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
from core.limits.concurrency import limit_concurrent_generations
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

# rag streams via a custom writer instead; including it here would double-emit its text.
_MESSAGES_MODE_NODES = frozenset({"answer", "tool"})

_CUSTOM_WRITER_NODES = frozenset({"rag"})

# Distinguishes an actual guardrail block from the plain "unclear intent" case; both route through the same guardrail node.
_GUARDRAIL_BLOCKED_ERRORS = frozenset({"input_rail_blocked", "output_rail_blocked"})

# Process-local retry lock for concurrent duplicate turns; doesn't cover cross-replica races (needs a distributed lock for that).
_INFLIGHT_TURNS: dict[tuple[UUID, str], asyncio.Event] = {}


@asynccontextmanager
async def _unit_of_work(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Same contract as core.db.engine.get_session, usable outside FastAPI's Depends."""
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@dataclass(slots=True)
class TurnContext:
    """Handoff from begin_turn to the streaming step; replay carries a prior turn's reply so retries don't re-run the graph."""

    conversation_id: UUID
    user_id: UUID
    text: str
    message_id: UUID
    user_message_id: UUID
    replay: Message | None
    inflight_key: tuple[UUID, str] | None = None


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
                # Explicit [], not None: create_idempotent's raw INSERT would serialize None as JSON null, failing MessageRead's list validation.
                artifacts=[],
                citations=[],
                idempotency_key=idempotency_key,
            )
            inserted_user_message, created = await messages.create_idempotent(user_message)

            replay: Message | None = None
            if not created:
                replay = await self._existing_reply(messages, inserted_user_message.id)

        # Below runs outside the transaction above -- never hold a session open across turn-length work.
        inflight_key: tuple[UUID, str] | None = None
        if idempotency_key is not None:
            key = (conversation_id, idempotency_key)
            if created:
                _INFLIGHT_TURNS[key] = asyncio.Event()
                inflight_key = key
            elif replay is None:
                replay = await self._await_inflight_then_recheck(
                    key, user_message_id=inserted_user_message.id
                )

        return TurnContext(
            conversation_id=conversation_id,
            user_id=user_id,
            text=text,
            message_id=uuid4(),
            user_message_id=inserted_user_message.id,
            replay=replay,
            inflight_key=inflight_key,
        )

    @staticmethod
    async def _existing_reply(messages: MessageRepository, user_message_id: UUID) -> Message | None:
        return await messages.get_reply_to(user_message_id)

    async def _await_inflight_then_recheck(
        self, key: tuple[UUID, str], *, user_message_id: UUID
    ) -> Message | None:
        # Bounded by TURN_BUDGET_SECONDS so a dead original attempt that never released the marker doesn't hang this one forever.
        event = _INFLIGHT_TURNS.get(key)
        if event is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(event.wait(), timeout=self._settings.TURN_BUDGET_SECONDS)

        async with _unit_of_work(self._sessionmaker) as session:
            return await self._existing_reply(MessageRepository(session), user_message_id)

    # --- Simple mode ---------------------------------------------------------

    async def stream_turn_simple(self, turn: TurnContext) -> AsyncIterator[ServerSentEvent]:
        formatter = SSEEventFormatter()
        async for event in self._run_turn(turn, stream_id=None):
            yield formatter.format(event)

    # --- Durable mode ----------------------------------------------------------

    async def run_durable_producer(self, *, stream_id: str, turn: TurnContext) -> None:
        """Runs independently of the originating request; always publishes the end-of-stream sentinel so tailers stop waiting."""
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

        try:
            async for event in self._generate_and_persist(turn, stream_id=stream_id):
                yield event
        finally:
            # Release only once this generator is fully done, so a waiting retry (_await_inflight_then_recheck) stops waiting.
            if turn.inflight_key is not None:
                inflight_event = _INFLIGHT_TURNS.pop(turn.inflight_key, None)
                if inflight_event is not None:
                    inflight_event.set()

    async def _generate_and_persist(
        self, turn: TurnContext, *, stream_id: str | None
    ) -> AsyncIterator[ChatSSEEvent]:
        translator = _EventTranslator(
            conversation_id=turn.conversation_id, message_id=turn.message_id, stream_id=stream_id
        )
        final_state: dict[str, Any] = {}
        try:
            # Covers only the graph run itself, not persistence or SSE tailing below.
            async with limit_concurrent_generations():
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
            # Client already received the full reply via SSE; a persist failure here is a durability issue to alert on, not a stream error.
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
                    reply_to_message_id=turn.user_message_id,
                )
            )

    # --- Durable-mode stream ownership --------------------------------------

    async def record_stream_owner(self, *, stream_id: str, user_id: UUID) -> None:
        """Called before the response carrying X-Stream-Id returns, so no window exists where the id exists without an owner record."""
        assert self._stream_bus is not None
        await self._stream_bus.record_owner(stream_id, str(user_id))

    async def is_stream_owner(self, *, stream_id: str, user_id: UUID) -> bool:
        """Fails open (True) when there's no owner on record, rather than turning a TTL expiry into a false rejection."""
        assert self._stream_bus is not None
        owner = await self._stream_bus.get_owner(stream_id)
        return owner is None or owner == str(user_id)


def _replay_events(message: Message, *, message_id: UUID) -> list[ChatSSEEvent]:
    """Replays a prior turn's persisted reply under its own message id, not this retry's."""
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


# Module-level, not instance state: chat_streamer is a per-request DI factory, but spawn/cancel must share one process-global map.
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
    """Duplicated from agents/chat/nodes/_util.py, which is private to that package."""
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
    """Stateful per turn -- construct fresh per _run_turn call."""

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
            return []

        return self._handle_branch_completion(node_name, update)

    def _handle_branch_completion(
        self, node_name: str, update: Mapping[str, Any]
    ) -> list[ChatSSEEvent]:
        events: list[ChatSSEEvent] = []

        if node_name == "guardrail":
            # "refuse" when input_rail/output_rail actually blocked something; "clarify" for the plain unclear-intent case.
            action = "refuse" if update.get("error") in _GUARDRAIL_BLOCKED_ERRORS else "clarify"
            events.append(GuardrailEvent(action=action, message=str(update.get("answer") or "")))

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

    # -- "messages": auto-streamed model output ------------------------------

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

    # -- "custom": whatever a node pushed via get_stream_writer() ------------

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
