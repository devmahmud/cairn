"""TypedDict, not a Pydantic model -- StateGraph merges each node's return by key, and checkpointing needs every field JSON-safe."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict, total=False):
    # add_messages appends by message id (replacing on match), LangGraph's standard chat-history reducer.
    messages: Annotated[list[AnyMessage], add_messages]

    # Duplicated from RunnableConfig's thread_id so a node can read it without reaching into graph config.
    conversation_id: str
    user_id: str | None

    input: str

    intent: str | None
    confidence: float | None

    # One of "answer"/"rag"/"tool"/"guardrail", consumed by route's conditional edge.
    route: str | None

    retrieved: list[dict[str, Any]]
    citations: list[dict[str, Any]]

    answer: str | None
    abstained: bool

    # Capped via MAX_GRAPH_HOPS.
    hops: int

    # Short machine code (e.g. "rag_empty"), not user-facing -- answer already carries the graceful message.
    error: str | None
