"""`ChatAgent` -- the graph, wrapped with the turn-level durability contract (BLUEPRINT.md §3.6, §8 step 5).

Builds the compiled graph (`agents/chat/graph.py`) once and exposes a single
`ainvoke()` that a REST/CLI/streaming caller drives one turn through. Two
things live at this layer, not inside the graph itself, because they're
properties of *running* the graph for one turn rather than the graph's
structure:

- **`durability="sync"`** (§3.6: "a chat turn is not high-enough-throughput
  for the latency difference to matter, and losing a step silently is worse
  than the extra round-trip") -- the checkpoint for each node is written
  *before* the next node runs. Only applied when a checkpointer is actually
  configured; `checkpointer=None` (a real, supported case -- see
  `agents/chat/graph.py`) runs the graph without it instead of passing a
  `durability` value LangGraph doesn't support in that combination.
- **`TURN_BUDGET_SECONDS`** -- the wall-clock budget wrapping the *whole*
  graph run, on top of (not instead of) every node's own timeout
  (`agents/chat/graph.py`'s `timeout=` per node) and the fallback ladder
  each node implements internally.

This is also the DI container's `chat_agent` provider target
(`core/di/container.py`): `Container.chat_agent = providers.Singleton(ChatAgent, ...)`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, cast
from uuid import UUID

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Durability

from agents.chat.graph import build_chat_graph
from agents.chat.nodes._protocols import BehaviorSource
from agents.chat.state import ChatState
from agents.llm import get_llm
from core.config import Settings, settings
from core.prompts.engine import PromptEngine
from modules.retrieval.protocol import RetrievalService

logger = structlog.get_logger(__name__)

_TURN_BUDGET_MESSAGE = "That's taking longer than expected -- please try again in a moment."


class ChatAgent:
    def __init__(
        self,
        *,
        prompt_engine: PromptEngine,
        retrieval_service: RetrievalService,
        checkpointer: BaseCheckpointSaver | None,
        behavior_config: BehaviorSource,
        llm_factory: Callable[[str], BaseChatModel] = get_llm,
        app_settings: Settings = settings,
    ) -> None:
        self._settings = app_settings
        # `graph.astream/ainvoke(durability=...)` only has an effect when a
        # checkpointer is actually present -- LangGraph itself warns as much
        # when `checkpointer=None` (a real, supported combination here: an
        # eval harness or a unit test that doesn't need persistence,
        # `agents/chat/graph.py`'s own `checkpointer: BaseCheckpointSaver |
        # None` signature). Passing `durability="sync"` anyway isn't just a
        # no-op in that case -- it hits an internal LangGraph code path that
        # assumes a checkpointer is wired up and raises. Compute once, at
        # construction, which value is actually safe to pass per call.
        self._durability: Durability | None = "sync" if checkpointer is not None else None
        self._graph = build_chat_graph(
            prompt_engine=prompt_engine,
            retrieval_service=retrieval_service,
            behavior_config=behavior_config,
            checkpointer=checkpointer,
            llm_factory=llm_factory,
            app_settings=app_settings,
        )

    async def ainvoke(
        self, *, conversation_id: UUID | str, user_id: UUID | str | None, text: str
    ) -> ChatState:
        """Run one turn to completion and return the graph's final state.

        `thread_id` is `str(conversation_id)` -- a UUID string -- per §3.6's
        note that the checkpointer's `thread_id` column is bounded, so a
        conversation's id (not free text) is what identifies its checkpoint
        history. Calling this again with the same `conversation_id` resumes
        that same thread's graph state rather than starting fresh -- that's
        what makes a crash mid-graph recoverable (§3.3, §3.6).
        """
        thread_id = str(conversation_id)
        input_state: ChatState = {
            "messages": [HumanMessage(content=text)],
            "conversation_id": thread_id,
            "user_id": str(user_id) if user_id is not None else None,
            "input": text,
            "hops": 0,
            "abstained": False,
            "error": None,
        }
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        try:
            async with asyncio.timeout(self._settings.TURN_BUDGET_SECONDS):
                result = await self._graph.ainvoke(
                    input_state, config=config, durability=self._durability
                )
        except TimeoutError:
            logger.warning(
                "chat_agent.turn_budget_exceeded",
                thread_id=thread_id,
                turn_budget_seconds=self._settings.TURN_BUDGET_SECONDS,
            )
            return {
                **input_state,
                "messages": [*input_state["messages"], AIMessage(content=_TURN_BUDGET_MESSAGE)],
                "answer": _TURN_BUDGET_MESSAGE,
                "citations": [],
                "error": "turn_budget_exceeded",
            }

        return cast(ChatState, result)

    async def astream(
        self, *, conversation_id: UUID | str, user_id: UUID | str | None, text: str
    ) -> AsyncIterator[tuple[str, Any]]:
        """Run one turn, yielding `(stream_mode, payload)` as the graph produces it.

        The streaming counterpart to `ainvoke` -- same `thread_id`/input-state
        setup and the same `TURN_BUDGET_SECONDS` wall-clock budget (§3.6), but
        yields incrementally instead of returning only the final state, for
        `modules/chat/chat_stream.py`'s translator to turn into SSE events.
        `stream_mode=["updates", "messages", "custom"]` (§3.6, §3.7) is the
        one place this template calls `graph.astream` with all three modes
        multiplexed:
        - `"updates"` -- each node's partial state update as it completes
          (drives `agent_switch`/`decision`/`guardrail`/`message_end`).
        - `"messages"` -- token-by-token model output, auto-streamed by
          LangGraph for any node's plain (non-tool-bound, non-structured-
          output) LLM call, even one made via a plain `.ainvoke()` -- the
          "plain-text node" half of §3.6's streaming-technique correction.
        - `"custom"` -- whatever a node explicitly pushes via
          `get_stream_writer()` (`agents/chat/nodes/rag.py`'s answer
          generation, `tool.py`'s per-call results) -- the "structured/
          forced-tool node" half, since `"messages"` only carries tool-call
          chunks for those.

        A turn-budget timeout yields one final `("timeout", {...})` tuple --
        not a plain state dict shaped like `ainvoke`'s return, since a
        streaming caller has no single "the result" to hand back; the
        translator treats this sentinel mode as a mid-turn `error` event
        (§3.7: "the HTTP error path is gone once bytes flow").
        """
        thread_id = str(conversation_id)
        input_state: ChatState = {
            "messages": [HumanMessage(content=text)],
            "conversation_id": thread_id,
            "user_id": str(user_id) if user_id is not None else None,
            "input": text,
            "hops": 0,
            "abstained": False,
            "error": None,
        }
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        try:
            async with asyncio.timeout(self._settings.TURN_BUDGET_SECONDS):
                async for mode, payload in self._graph.astream(
                    input_state,
                    config=config,
                    stream_mode=["updates", "messages", "custom"],
                    durability=self._durability,
                ):
                    yield mode, payload
        except TimeoutError:
            logger.warning(
                "chat_agent.turn_budget_exceeded",
                thread_id=thread_id,
                turn_budget_seconds=self._settings.TURN_BUDGET_SECONDS,
            )
            yield (
                "timeout",
                {
                    "answer": _TURN_BUDGET_MESSAGE,
                    "citations": [],
                    "error": "turn_budget_exceeded",
                },
            )
