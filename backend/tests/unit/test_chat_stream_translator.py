"""Drives the real chat graph with a fake LLM through `ChatAgent.astream` and
`modules.chat.chat_stream._EventTranslator`, asserting a well-formed SSE
event sequence (BLUEPRINT.md §3.6, §3.7, §8 step 6's acceptance check).

No Postgres, no network, no HTTP layer -- `checkpointer=None` (as in
`tests/unit/test_chat_graph_offline.py`) and `FakeChatModel` stand in for the
two things that would otherwise require a running service. What this *does*
exercise for real: the actual `agents/chat/graph.py` graph, the actual
`stream_mode=["updates","messages","custom"]` multiplexing LangGraph does,
`rag.py`'s custom-writer streaming and `tool.py`'s per-call `tool_result`
writes, and `chat_stream.py`'s translation of all of that into
`modules.chat.sse` wire events -- i.e. everything `ChatStreamer._run_turn`
does except the two DB transactions either side of it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agents.chat.agent import ChatAgent
from agents.chat.schemas import ClassifyResult
from core.behavior.loader import BehaviorConfig
from core.prompts.engine import PromptEngine
from core.prompts.loader import FileSystemJ2Loader
from modules.chat.chat_stream import _EventTranslator
from modules.chat.sse import (
    AgentSwitchEvent,
    ChatSSEEvent,
    DecisionEvent,
    ErrorEvent,
    GuardrailEvent,
    MessageDeltaEvent,
    MessageEndEvent,
    MessageStartEvent,
    ToolResultEvent,
)
from modules.retrieval.fixture import LocalFixtureRetrievalService
from tests.unit.fakes import FakeChatModel

_CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"
_MESSAGE_ID = "22222222-2222-2222-2222-222222222222"


def _make_agent(fakes: dict[str, FakeChatModel]) -> ChatAgent:
    def llm_factory(role: str) -> BaseChatModel:
        try:
            return fakes[role]
        except KeyError:
            raise AssertionError(f"No fake LLM configured for role {role!r}.") from None

    return ChatAgent(
        prompt_engine=PromptEngine(loader=FileSystemJ2Loader(base_path="config/prompts")),
        retrieval_service=LocalFixtureRetrievalService(),
        checkpointer=None,
        behavior_config=BehaviorConfig(base_path="config/behavior"),
        llm_factory=llm_factory,
    )


async def _drive(agent: ChatAgent, *, text: str) -> list[ChatSSEEvent]:
    translator = _EventTranslator(
        conversation_id=_CONVERSATION_ID,  # type: ignore[arg-type]
        message_id=_MESSAGE_ID,  # type: ignore[arg-type]
        stream_id=None,
    )
    events: list[ChatSSEEvent] = []
    async for mode, payload in agent.astream(
        conversation_id=_CONVERSATION_ID, user_id=None, text=text
    ):
        assert mode != "timeout", "not expected in these fast, fake-LLM-backed scenarios"
        events.extend(translator.handle(mode, payload))
    return events


def _types(events: list[ChatSSEEvent]) -> list[str]:
    return [event.type for event in events]


async def test_greeting_turn_yields_a_well_formed_answer_sequence() -> None:
    fakes = {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="greeting", confidence=0.95)
        ),
        "answer": FakeChatModel(responses=[AIMessage(content="Hi there! How can I help?")]),
    }
    events = await _drive(_make_agent(fakes), text="hello!")

    assert _types(events) == [
        "decision",
        "agent_switch",
        "message_start",
        "message_delta",
        "message_end",
    ]

    decision = events[0]
    assert isinstance(decision, DecisionEvent)
    assert decision.intent == "greeting"

    agent_switch = events[1]
    assert isinstance(agent_switch, AgentSwitchEvent)
    assert agent_switch.agent == "answer"

    start = events[2]
    assert isinstance(start, MessageStartEvent)
    assert start.message_id == _MESSAGE_ID
    assert start.conversation_id == _CONVERSATION_ID
    assert start.stream_id is None

    delta = events[3]
    assert isinstance(delta, MessageDeltaEvent)
    assert delta.text == "Hi there! How can I help?"
    assert delta.message_id == _MESSAGE_ID

    end = events[4]
    assert isinstance(end, MessageEndEvent)
    assert end.citations == []


async def test_rag_turn_streams_via_custom_writer_and_ends_with_citations() -> None:
    fakes = {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="product_question", confidence=0.9)
        ),
        "rag": FakeChatModel(
            responses=[AIMessage(content="Send your API key as a bearer token [1].")]
        ),
    }
    events = await _drive(_make_agent(fakes), text="How do I authenticate my requests to the API?")

    assert _types(events) == [
        "decision",
        "agent_switch",
        "message_start",
        "message_delta",
        "message_end",
    ]

    agent_switch = events[1]
    assert isinstance(agent_switch, AgentSwitchEvent)
    assert agent_switch.agent == "rag"

    delta = events[3]
    assert isinstance(delta, MessageDeltaEvent)
    assert delta.text == "Send your API key as a bearer token [1]."

    end = events[4]
    assert isinstance(end, MessageEndEvent)
    assert len(end.citations) > 0
    assert end.citations[0].index == 1


async def test_unclear_intent_routes_to_guardrail_with_a_guardrail_event() -> None:
    fakes = {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="unclear", confidence=0.9)
        ),
    }
    events = await _drive(_make_agent(fakes), text="???")

    assert _types(events) == [
        "decision",
        "agent_switch",
        "message_start",
        "guardrail",
        "message_delta",
        "message_end",
    ]

    agent_switch = events[1]
    assert isinstance(agent_switch, AgentSwitchEvent)
    assert agent_switch.agent == "guardrail"

    guardrail = events[3]
    assert isinstance(guardrail, GuardrailEvent)
    assert guardrail.action == "clarify"
    assert "rephrase" in guardrail.message.lower()

    delta = events[4]
    assert isinstance(delta, MessageDeltaEvent)
    assert delta.text == guardrail.message


async def test_tool_turn_emits_tool_result_events_then_the_final_answer() -> None:
    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "web_search",
                "args": {"query": "current version"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    final_response = AIMessage(content="I looked into it: web search isn't configured here.")
    fakes = {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="web_search", confidence=0.9)
        ),
        "tool": FakeChatModel(responses=[tool_call_response, final_response]),
    }
    events = await _drive(_make_agent(fakes), text="What's the latest version?")

    assert _types(events) == [
        "decision",
        "agent_switch",
        "message_start",
        "tool_result",
        "message_delta",
        "message_end",
    ]

    tool_result = events[3]
    assert isinstance(tool_result, ToolResultEvent)
    assert tool_result.tool_name == "web_search"

    delta = events[4]
    assert isinstance(delta, MessageDeltaEvent)
    assert delta.text == "I looked into it: web search isn't configured here."


async def test_rag_generation_failure_still_ends_the_turn_with_an_error_event() -> None:
    class _RaisingLLM(FakeChatModel):
        async def astream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
            raise RuntimeError("provider outage")
            yield  # pragma: no cover -- makes this an async generator

    fakes = {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="product_question", confidence=0.9)
        ),
        "rag": _RaisingLLM(),
    }
    events = await _drive(_make_agent(fakes), text="How do I authenticate my requests to the API?")

    assert _types(events) == [
        "decision",
        "agent_switch",
        "message_start",
        "error",
        "message_delta",
        "message_end",
    ]

    error = events[3]
    assert isinstance(error, ErrorEvent)
    assert error.code == "rag_generation_failed"
