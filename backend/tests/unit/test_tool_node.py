"""Unit test for the same conversation-memory fix in `agents.chat.nodes.tool.ToolAgentNode`
as test_answer_node.py / test_rag_node.py cover for their nodes."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage

from agents.chat.nodes.tool import ToolAgentNode
from agents.chat.state import ChatState
from tests.unit.fakes import FakeChatModel


async def test_includes_prior_turns_alongside_the_current_question() -> None:
    prior: list[AnyMessage] = [
        HumanMessage(content="what's the date?"),
        AIMessage(content="It's 2026-08-18."),
    ]
    fake = FakeChatModel(responses=[AIMessage(content="No tool needed for that.")])
    node = ToolAgentNode(llm_factory=lambda role: fake)
    state: ChatState = {
        "input": "and yesterday?",
        "messages": [*prior, HumanMessage(content="and yesterday?")],
    }

    await node(state)

    [sent] = fake.received_messages
    assert isinstance(sent[0], SystemMessage)
    assert sent[1:] == [*prior, HumanMessage(content="and yesterday?")]
