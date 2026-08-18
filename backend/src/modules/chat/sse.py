"""Chat SSE wire contract: snake_case in Python, camelCase on the wire; agents/ never emits SSE directly, only chat_stream.py's translator does."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import FastAPI
from fastapi.sse import ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic.alias_generators import to_camel


class _WireModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Citation(_WireModel):
    """Field names mirror agents/chat/nodes/rag.py's citation dict shape, so Citation(**entry) works directly."""

    index: int
    chunk_id: str
    document_id: str
    source: str | None = None
    score: float


class MessageStartEvent(_WireModel):
    type: Literal["message_start"] = "message_start"
    message_id: str
    conversation_id: str
    # Only set in durable mode; also mirrored onto the X-Stream-Id header for consumers that only see the event stream.
    stream_id: str | None = None


class MessageDeltaEvent(_WireModel):
    type: Literal["message_delta"] = "message_delta"
    message_id: str
    text: str


class MessageEndEvent(_WireModel):
    type: Literal["message_end"] = "message_end"
    message_id: str
    citations: list[Citation] = Field(default_factory=list)


class AgentSwitchEvent(_WireModel):
    """Emitted once per turn, right after route decides, before that branch's message_start."""

    type: Literal["agent_switch"] = "agent_switch"
    agent: str


class ToolResultEvent(_WireModel):
    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    result: str


class DecisionEvent(_WireModel):
    """classify's {intent, confidence}; not message text -- for a debug/trace panel."""

    type: Literal["decision"] = "decision"
    intent: str
    confidence: float


class GuardrailEvent(_WireModel):
    """action is a short machine code, kept separate from message, the user-facing text."""

    type: Literal["guardrail"] = "guardrail"
    action: str
    message: str


class ErrorEvent(_WireModel):
    """code mirrors the graph state's error field (a machine code); message is safe to show a user as-is."""

    type: Literal["error"] = "error"
    code: str
    message: str


ChatSSEEvent = Annotated[
    MessageStartEvent
    | MessageDeltaEvent
    | MessageEndEvent
    | AgentSwitchEvent
    | ToolResultEvent
    | DecisionEvent
    | GuardrailEvent
    | ErrorEvent,
    Field(discriminator="type"),
]

_CHAT_SSE_EVENT_ADAPTER: TypeAdapter[ChatSSEEvent] = TypeAdapter(ChatSSEEvent)
_CHAT_SSE_EVENT_SCHEMA_NAME = "ChatSSEEvent"


class SSEEventFormatter:
    """Stamps a monotonic id per event; format() targets simple mode, format_raw() is the same triple XADD'd verbatim for durable mode."""

    def __init__(self) -> None:
        self._next_id = 1

    def format_raw(self, event: ChatSSEEvent) -> tuple[str, str, str]:
        event_id = str(self._next_id)
        self._next_id += 1
        return event_id, event.type, event.model_dump_json(by_alias=True)

    def format(self, event: ChatSSEEvent) -> ServerSentEvent:
        event_id, event_type, data_json = self.format_raw(event)
        return ServerSentEvent(id=event_id, event=event_type, raw_data=data_json)


def register_sse_schema(app: FastAPI) -> None:
    """SSE responses bypass response_model, so this merges ChatSSEEvent's schema into /openapi.json via FastAPI's "extending OpenAPI" recipe."""
    schema = _CHAT_SSE_EVENT_ADAPTER.json_schema(ref_template="#/components/schemas/{model}")
    member_schemas: dict[str, Any] = schema.pop("$defs", {})
    member_schemas[_CHAT_SSE_EVENT_SCHEMA_NAME] = schema

    original_openapi = app.openapi

    def _custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = original_openapi()
        components = openapi_schema.setdefault("components", {})
        schemas = components.setdefault("schemas", {})
        schemas.update(member_schemas)
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = _custom_openapi  # type: ignore[method-assign]
