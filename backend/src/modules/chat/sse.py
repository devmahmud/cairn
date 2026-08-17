"""The chat SSE wire contract (BLUEPRINT.md §3.7, §8 step 6).

Pydantic `_WireModel`s, snake_case in Python / camelCase on the wire (every
model shares `_WireModel`'s `alias_generator=to_camel`). The core event set:
`message_start · message_delta · message_end (+citations) · agent_switch ·
tool_result · decision · guardrail · error` -- domain-specific events (e.g. a
`slot_fill`) belong to an `examples/` pack, not here.

`agents/` emits no SSE (§3.1, §3.6); `modules/chat/chat_stream.py`'s
`_EventTranslator` is the one place that turns a graph `(mode, payload)`
tuple into one of the models below. `SSEEventFormatter` is the other half of
this module: it stamps the monotonic `id:` every event carries on the wire,
which is what makes `Last-Event-ID` resume (§3.7) possible in durable mode --
and is a no-op-but-still-present convenience even in simple mode, where
FastAPI's native `EventSourceResponse` (§1) gets `Last-Event-ID` handling for
free without this template needing `sse-starlette`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import FastAPI
from fastapi.sse import ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic.alias_generators import to_camel


class _WireModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Citation(_WireModel):
    """One retrieved-and-cited passage backing a `rag`-routed answer (§3.8).

    Field names deliberately mirror `agents/chat/nodes/rag.py`'s own
    citation dict shape (`index/chunk_id/document_id/source/score`) so the
    streamer's translator can build one of these straight from a graph
    `citations` update via `Citation(**entry)`.
    """

    index: int
    chunk_id: str
    document_id: str
    source: str | None = None
    score: float


class MessageStartEvent(_WireModel):
    type: Literal["message_start"] = "message_start"
    message_id: str
    conversation_id: str
    #: Only set in durable mode (§3.7) -- the Redis-stream key a client
    #: reconnects to via `GET /chat/stream/{stream_id}`. Also mirrored onto
    #: the `X-Stream-Id` response header so a client can read it before the
    #: body starts streaming; carried here too so it's available to any
    #: consumer that only sees the event stream itself.
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
    """The graph committed to one branch (`answer`/`rag`/`tool`/`guardrail`, §3.6).

    Emitted once per turn, right after the `route` node decides -- before
    that branch's `message_start`.
    """

    type: Literal["agent_switch"] = "agent_switch"
    agent: str


class ToolResultEvent(_WireModel):
    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    result: str


class DecisionEvent(_WireModel):
    """The `classify` node's `{intent, confidence}` (§3.6) -- not shown as
    message text, surfaced as its own event for a debug/trace panel."""

    type: Literal["decision"] = "decision"
    intent: str
    confidence: float


class GuardrailEvent(_WireModel):
    """The `guardrail` node's verdict (§3.6, §3.12).

    `action` is a short machine code (`"clarify"` today -- the only verdict
    this node can reach before step 7 wires a real guard model; `"refuse"`/
    `"review"` are step 7's to add) kept separate from `message`, the
    user-facing text also carried by the paired `message_delta`/`message_end`.
    """

    type: Literal["guardrail"] = "guardrail"
    action: str
    message: str


class ErrorEvent(_WireModel):
    """A mid-turn failure (§3.7: "the HTTP error path is gone once bytes flow").

    `code` is a short machine code (mirrors the graph state's own `error`
    field, e.g. `"rag_generation_failed"`, `"turn_budget_exceeded"`) --
    `message` is safe to show a user as-is.
    """

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
    """Stamps a monotonic `id:` per event, one instance per turn/stream.

    Two output shapes for the same underlying (id, event-type, JSON body)
    triple, sharing one counter:
    - `format()` -- a `ServerSentEvent` for FastAPI's native
      `EventSourceResponse` (simple mode).
    - `format_raw()` -- the raw triple, for the durable-mode producer to
      `XADD` into Redis (`core/stream/resume.py`) verbatim; a tailer
      reconstructs the identical `ServerSentEvent` from those same three
      strings via `raw_data=` (pre-serialized, not re-encoded).
    """

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
    """Merge `ChatSSEEvent`'s schema into the app's OpenAPI `components/schemas`.

    SSE responses bypass FastAPI's normal `response_model` machinery (the
    chat router's endpoints stream `ServerSentEvent`s, not a declared
    response model), so nothing about `ChatSSEEvent` would otherwise reach
    `/openapi.json` -- and without it there, `openapi-typescript` (§4.3) has
    no discriminated union to generate the frontend's SSE dispatch types
    from. This follows FastAPI's own documented "extending OpenAPI" recipe:
    wrap `app.openapi`, call through to the original, then merge in the
    schema this module owns.
    """
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
