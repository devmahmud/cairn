"""Plain, ungrounded reply -- no retrieval, no tools. Distinct from rag, which grounds its answer in retrieved passages and can abstain."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.base import GraphNode
from agents.chat.nodes._util import content_to_text, today_iso
from agents.chat.state import ChatState
from agents.llm import get_llm
from agents.registry import register
from core.prompts.engine import PromptEngine

logger = structlog.get_logger(__name__)

_FALLBACK_MESSAGE = "Sorry, I ran into a problem answering that. Please try again."


@register
class AnswerNode(GraphNode[ChatState]):
    name = "answer"

    def __init__(
        self,
        *,
        prompt_engine: PromptEngine,
        llm_factory: Callable[[str], BaseChatModel] = get_llm,
        system_prompt_name: str = "docs_assistant/system.j2",
        assistant_name: str = "Cairn Docs Bot",
        product_name: str = "Cairn",
    ) -> None:
        self._prompt_engine = prompt_engine
        self._llm_factory = llm_factory
        self._system_prompt_name = system_prompt_name
        self._assistant_name = assistant_name
        self._product_name = product_name

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        question = state.get("input", "")
        try:
            system_prompt = await self._prompt_engine.render(
                self._system_prompt_name,
                assistant_name=self._assistant_name,
                product_name=self._product_name,
                current_date=today_iso(),
                tool_names=[],
            )
            llm = self._llm_factory("answer")
            response = await llm.ainvoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=question)]
            )
        except Exception:
            # Any failure here -- timeout, provider error, prompt-render error -- degrades to one graceful message rather than failing the turn.
            logger.warning("answer.failed_falling_back_to_graceful_message", exc_info=True)
            return {
                "messages": [AIMessage(content=_FALLBACK_MESSAGE)],
                "answer": _FALLBACK_MESSAGE,
                "citations": [],
                "error": "answer_failed",
            }

        text = content_to_text(response.content)
        return {"messages": [response], "answer": text, "citations": []}
