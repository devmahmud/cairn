"""Wraps the compiled graph with turn-level concerns (durability, wall-clock budget) that don't belong in the graph's own structure."""

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
        # durability="sync" requires a checkpointer -- LangGraph raises if passed anyway when checkpointer=None (e.g. tests without persistence).
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
        """Calling this again with the same conversation_id resumes that thread's checkpointed state rather than starting fresh."""
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
        """Streaming counterpart to ainvoke; multiplexes updates/messages/custom stream_mode. A timeout yields ("timeout", {...}) instead of ainvoke's state-shaped return."""
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
