"""Unit tests for `agents.chat.nodes.answer.AnswerNode` (BLUEPRINT.md §3.6).

Prior turns must reach the model, not just the current question -- same
regression class as test_rag_node.py's history tests: the graph durably
accumulates state["messages"], but each LLM-calling node has to actually
read it back to make the conversation feel conversational.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage

from agents.chat.nodes.answer import AnswerNode
from agents.chat.state import ChatState
from core.config import settings
from core.prompts.engine import PromptEngine
from core.prompts.loader import FileSystemJ2Loader
from tests.unit.fakes import FakeChatModel

_PROMPT_ENGINE = PromptEngine(loader=FileSystemJ2Loader(base_path="config/prompts"))


def _node(llm: FakeChatModel) -> AnswerNode:
    def llm_factory(role: str) -> FakeChatModel:
        assert role == "answer"
        return llm

    return AnswerNode(prompt_engine=_PROMPT_ENGINE, llm_factory=llm_factory)


async def test_sends_the_system_prompt_and_the_current_question() -> None:
    fake = FakeChatModel(responses=[AIMessage(content="Hi there!")])
    state: ChatState = {"input": "hello", "messages": [HumanMessage(content="hello")]}

    result = await _node(fake)(state)

    assert result["answer"] == "Hi there!"
    [sent] = fake.received_messages
    assert isinstance(sent[0], SystemMessage)
    assert sent[1:] == [HumanMessage(content="hello")]


async def test_includes_prior_turns_so_a_follow_up_has_context() -> None:
    prior: list[AnyMessage] = [
        HumanMessage(content="What was the previous question I asked?"),
        AIMessage(content="You asked how to authenticate."),
    ]
    fake = FakeChatModel(responses=[AIMessage(content="You asked about the weather.")])
    state: ChatState = {
        "input": "and before that?",
        "messages": [*prior, HumanMessage(content="and before that?")],
    }

    await _node(fake)(state)

    [sent] = fake.received_messages
    assert sent[1:] == [*prior, HumanMessage(content="and before that?")]


async def test_truncates_history_beyond_max_history_messages() -> None:
    prior: list[AnyMessage] = [HumanMessage(content=f"turn {i}") for i in range(40)]
    fake = FakeChatModel(responses=[AIMessage(content="ok")])
    state: ChatState = {"input": "latest", "messages": [*prior, HumanMessage(content="latest")]}

    await _node(fake)(state)

    [sent] = fake.received_messages
    assert len(sent) <= 1 + settings.MAX_HISTORY_MESSAGES


async def test_falls_back_gracefully_on_generation_failure() -> None:
    class _RaisingLLM(FakeChatModel):
        def _generate(self, *args: object, **kwargs: object) -> None:  # type: ignore[override]
            raise RuntimeError("provider is down")

    state: ChatState = {"input": "hello", "messages": [HumanMessage(content="hello")]}

    result = await _node(_RaisingLLM())(state)

    assert result["error"] == "answer_failed"
    assert "Please try again" in result["answer"]
