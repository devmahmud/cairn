"""The chat graph's state schema (BLUEPRINT.md §3.6, §8 step 5).

A `TypedDict`, not a Pydantic model -- LangGraph merges each node's partial
return value onto this by key (via `Annotated[..., <reducer>]` for
`messages`, plain last-write-wins for everything else), and `StateGraph`
expects that merge contract on a plain mapping type. `chat/schemas.py`
holds the *structured-output* schemas (Pydantic, for `with_structured_output`)
-- a different concern from the graph's own state shape.

`retrieved`/`citations` are plain JSON-safe `dict`s, not
`modules.retrieval.protocol.RetrievalDoc` instances -- the checkpointer
persists this state via `AsyncPostgresSaver` (§3.3), and keeping every field
representable as plain JSON is the simplest way to guarantee that survives
serialization/deserialization across a process restart without coupling the
graph's checkpoint format to a Pydantic model's schema evolution.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict, total=False):
    # The running turn transcript. `add_messages` appends by message `id`
    # (replacing on a matching id) rather than overwriting the list --
    # LangGraph's standard reducer for a chat history field.
    messages: Annotated[list[AnyMessage], add_messages]

    # `thread_id` for the checkpointer is `str(conversation_id)` (§3.6) --
    # stored again here (not just in `RunnableConfig`) so a node can read it
    # without reaching into graph config.
    conversation_id: str
    user_id: str | None

    # This turn's raw user input, set once by `ChatAgent.ainvoke` before the
    # graph runs.
    input: str

    # `classify` node output.
    intent: str | None
    confidence: float | None

    # `route` node output -- one of "answer" / "rag" / "tool" / "guardrail",
    # consumed by the conditional edge dispatching out of `route`
    # (`agents/chat/graph.py`).
    route: str | None

    # `rag` node output: the (possibly reranked) passages it grounded the
    # answer on, and the citation list derived from them.
    retrieved: list[dict[str, Any]]
    citations: list[dict[str, Any]]

    # The worker nodes' (`answer`/`rag`/`tool`/`guardrail`) final text, and
    # whether it's a grounded answer or an abstention/deferral.
    answer: str | None
    abstained: bool

    # `tool` node's own hop counter (§3.6: "hop-capped via MAX_GRAPH_HOPS").
    hops: int

    # Set by any node's fallback-ladder branch (§3.6) -- a short machine
    # code (`"classify_timeout"`, `"rag_empty"`, `"tool_error"`,
    # `"turn_budget_exceeded"`, ...), not a user-facing string; `answer`
    # already carries the user-facing graceful message.
    error: str | None
