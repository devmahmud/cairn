"""Unit tests for `modules.chat.sse` (BLUEPRINT.md §3.7, §8 step 6).

Covers the wire contract itself: camelCase aliasing, the `type` discriminator,
`SSEEventFormatter`'s monotonic `id:` stamping (both output shapes sharing
one counter), and that `register_sse_schema` actually reaches
`/openapi.json`.
"""

from __future__ import annotations

from fastapi import FastAPI

from modules.chat.sse import (
    AgentSwitchEvent,
    Citation,
    DecisionEvent,
    ErrorEvent,
    GuardrailEvent,
    MessageDeltaEvent,
    MessageEndEvent,
    MessageStartEvent,
    SSEEventFormatter,
    ToolResultEvent,
    register_sse_schema,
)


def test_message_start_serializes_camel_case_with_optional_stream_id() -> None:
    event = MessageStartEvent(message_id="m1", conversation_id="c1")

    assert event.model_dump(by_alias=True) == {
        "type": "message_start",
        "messageId": "m1",
        "conversationId": "c1",
        "streamId": None,
    }


def test_message_end_serializes_citations_camel_case() -> None:
    event = MessageEndEvent(
        message_id="m1",
        citations=[
            Citation(index=1, chunk_id="chunk-1", document_id="doc-1", source="a.md", score=0.9)
        ],
    )

    dumped = event.model_dump(by_alias=True)
    assert dumped["citations"] == [
        {
            "index": 1,
            "chunkId": "chunk-1",
            "documentId": "doc-1",
            "source": "a.md",
            "score": 0.9,
        }
    ]


def test_every_event_type_populates_by_field_name_too() -> None:
    # `populate_by_name=True` on `_WireModel` -- constructing from Python
    # kwargs (snake_case) must keep working even though the wire alias is
    # camelCase (§3.7).
    assert AgentSwitchEvent(agent="rag").agent == "rag"
    assert DecisionEvent(intent="greeting", confidence=0.9).confidence == 0.9
    assert GuardrailEvent(action="clarify", message="huh?").action == "clarify"
    assert ToolResultEvent(tool_name="web_search", result="ok").tool_name == "web_search"
    assert ErrorEvent(code="boom", message="oops").code == "boom"
    assert MessageDeltaEvent(message_id="m1", text="hi").text == "hi"


def test_format_event_stamps_monotonic_ids_across_event_types() -> None:
    formatter = SSEEventFormatter()

    start = formatter.format(MessageStartEvent(message_id="m1", conversation_id="c1"))
    delta = formatter.format(MessageDeltaEvent(message_id="m1", text="Hi"))
    end = formatter.format(MessageEndEvent(message_id="m1"))

    assert [start.id, delta.id, end.id] == ["1", "2", "3"]
    assert [start.event, delta.event, end.event] == [
        "message_start",
        "message_delta",
        "message_end",
    ]
    # The wire payload is pre-serialized JSON, not re-encoded by the SSE layer.
    assert start.raw_data is not None
    assert '"messageId":"m1"' in start.raw_data
    assert start.data is None


def test_format_raw_shares_the_same_counter_as_format() -> None:
    formatter = SSEEventFormatter()

    first_id, first_type, first_json = formatter.format_raw(
        MessageDeltaEvent(message_id="m1", text="a")
    )
    second = formatter.format(MessageDeltaEvent(message_id="m1", text="b"))

    assert first_id == "1"
    assert first_type == "message_delta"
    assert '"text":"a"' in first_json
    assert second.id == "2"


def test_two_formatters_count_independently() -> None:
    # One instance per turn/stream (`ChatStreamer`'s docstring) -- a fresh
    # counter per turn, not a shared/global one.
    a, b = SSEEventFormatter(), SSEEventFormatter()

    assert a.format(MessageDeltaEvent(message_id="m1", text="x")).id == "1"
    assert b.format(MessageDeltaEvent(message_id="m2", text="y")).id == "1"
    assert a.format(MessageDeltaEvent(message_id="m1", text="z")).id == "2"


def test_register_sse_schema_reaches_openapi_components() -> None:
    app = FastAPI()
    register_sse_schema(app)

    schema = app.openapi()

    component_names = set(schema["components"]["schemas"])
    assert "ChatSSEEvent" in component_names
    for expected in (
        "MessageStartEvent",
        "MessageDeltaEvent",
        "MessageEndEvent",
        "AgentSwitchEvent",
        "ToolResultEvent",
        "DecisionEvent",
        "GuardrailEvent",
        "ErrorEvent",
        "Citation",
    ):
        assert expected in component_names

    chat_sse_event = schema["components"]["schemas"]["ChatSSEEvent"]
    assert "oneOf" in chat_sse_event
    assert chat_sse_event["discriminator"]["propertyName"] == "type"


def test_register_sse_schema_caches_the_openapi_schema() -> None:
    app = FastAPI()
    register_sse_schema(app)

    first = app.openapi()
    second = app.openapi()

    assert first is second
