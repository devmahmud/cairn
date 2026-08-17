"""Offline, end-to-end chat-graph runs (BLUEPRINT.md §8 step 5's acceptance check).

"the graph should run offline via a CLI or a unit test (no network) using
`LocalFixtureRetrievalService` and a fake/stub LLM -- confirm classify ->
route -> answer/rag produces a result end-to-end without hitting a real
Postgres or a real model API."

No Postgres (`checkpointer=None`, so there's nothing to persist -- a real
deployment uses `AsyncPostgresSaver`, wired in `core/di/container.py`), no
network (`LocalFixtureRetrievalService` + `FakeChatModel`, `tests/unit/fakes.py`).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from agents.chat.agent import ChatAgent
from agents.chat.schemas import ClassifyResult
from core.behavior.loader import BehaviorConfig
from core.prompts.engine import PromptEngine
from core.prompts.loader import FileSystemJ2Loader
from modules.retrieval.fixture import LocalFixtureRetrievalService
from tests.unit.fakes import FakeChatModel


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


async def test_greeting_routes_to_answer() -> None:
    fakes = {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="greeting", confidence=0.95)
        ),
        "answer": FakeChatModel(responses=[AIMessage(content="Hi there! How can I help?")]),
    }
    agent = _make_agent(fakes)

    result = await agent.ainvoke(
        conversation_id="11111111-1111-1111-1111-111111111111", user_id=None, text="hello!"
    )

    assert result["route"] == "answer"
    assert result["answer"] == "Hi there! How can I help?"
    assert result["citations"] == []
    assert result["error"] is None


async def test_product_question_routes_to_rag_and_grounds_with_citations() -> None:
    fakes = {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="product_question", confidence=0.9)
        ),
        "rag": FakeChatModel(
            responses=[AIMessage(content="Send your API key as a bearer token [1].")]
        ),
    }
    agent = _make_agent(fakes)

    result = await agent.ainvoke(
        conversation_id="22222222-2222-2222-2222-222222222222",
        user_id="33333333-3333-3333-3333-333333333333",
        text="How do I authenticate my requests to the API?",
    )

    assert result["route"] == "rag"
    assert result["abstained"] is False
    assert result["answer"] == "Send your API key as a bearer token [1]."
    assert len(result["citations"]) > 0
    assert len(result["retrieved"]) > 0


async def test_unclear_high_confidence_routes_to_guardrail() -> None:
    fakes = {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="unclear", confidence=0.9)
        ),
    }
    agent = _make_agent(fakes)

    result = await agent.ainvoke(
        conversation_id="44444444-4444-4444-4444-444444444444", user_id=None, text="???"
    )

    assert result["route"] == "guardrail"
    assert result["abstained"] is True
    assert "rephrase" in (result["answer"] or "").lower()


async def test_web_search_intent_runs_bounded_tool_loop_to_completion() -> None:
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
    agent = _make_agent(fakes)

    result = await agent.ainvoke(
        conversation_id="55555555-5555-5555-5555-555555555555",
        user_id=None,
        text="What's the latest version?",
    )

    assert result["route"] == "tool"
    assert result["answer"] == "I looked into it: web search isn't configured here."
    assert result["hops"] == 1
