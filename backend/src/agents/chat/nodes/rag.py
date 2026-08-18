"""rag: retrieve -> abstain-or-ground -> cite. Retrieved passages are untrusted context to cite, never instructions to follow (OWASP LLM01)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.base import GraphNode
from agents.chat.nodes._protocols import BehaviorSource
from agents.chat.nodes._util import (
    content_to_text,
    recent_history,
    stream_writer_or_noop,
    today_iso,
)
from agents.chat.state import ChatState
from agents.llm import get_llm
from agents.registry import register
from core.prompts.engine import PromptEngine
from modules.retrieval.protocol import RetrievalDoc, RetrievalService

logger = structlog.get_logger(__name__)

_DEFAULT_TOP_K = 5
_DEFAULT_ABSTAIN_THRESHOLD = 0.15
# RRF scores top out ~0.033, far below a reranker-calibrated threshold -- comparing against that would abstain on every unreranked query.
_DEFAULT_ABSTAIN_THRESHOLD_UNRERANKED = 0.0

_ABSTAIN_MESSAGE = (
    "I found some related documentation, but nothing confident enough to "
    "answer that precisely -- could you rephrase, or point me at the "
    "specific guide you're looking at?"
)
_DEFER_MESSAGE = (
    "I don't have documentation covering that yet. Try rephrasing, or ask "
    "about something else in the docs."
)
_FALLBACK_MESSAGE = "Sorry, I ran into a problem answering that. Please try again."


@register
class RagNode(GraphNode[ChatState]):
    name = "rag"

    def __init__(
        self,
        *,
        prompt_engine: PromptEngine,
        retrieval_service: RetrievalService,
        behavior_config: BehaviorSource,
        llm_factory: Callable[[str], BaseChatModel] = get_llm,
        answer_prompt_name: str = "docs_assistant/answer.j2",
        system_prompt_name: str = "docs_assistant/system.j2",
        assistant_name: str = "Cairn Docs Bot",
        product_name: str = "Cairn",
    ) -> None:
        self._prompt_engine = prompt_engine
        self._retrieval_service = retrieval_service
        self._behavior_config = behavior_config
        self._llm_factory = llm_factory
        self._answer_prompt_name = answer_prompt_name
        self._system_prompt_name = system_prompt_name
        self._assistant_name = assistant_name
        self._product_name = product_name

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        question = state.get("input", "")
        retrieval_cfg = await self._behavior_config.get("retrieval")
        top_k = int(retrieval_cfg.get("top_k", _DEFAULT_TOP_K))

        try:
            docs = await self._retrieval_service.query(question, top_k)
        except Exception:
            # A retrieval-layer failure gets the same "I don't have an answer" defer as no-results, not a hard turn failure.
            logger.warning("rag.retrieval_failed_deferring", exc_info=True)
            return _defer_result(error="rag_retrieval_failed")

        if not docs:
            logger.info("rag.no_results_deferring")
            return _defer_result()

        if docs[0].score_is_calibrated:
            abstain_threshold = float(
                retrieval_cfg.get("abstain_score_threshold", _DEFAULT_ABSTAIN_THRESHOLD)
            )
        else:
            abstain_threshold = float(
                retrieval_cfg.get(
                    "abstain_score_threshold_unreranked", _DEFAULT_ABSTAIN_THRESHOLD_UNRERANKED
                )
            )

        if docs[0].score < abstain_threshold:
            logger.info(
                "rag.top_score_below_abstain_threshold",
                top_score=docs[0].score,
                threshold=abstain_threshold,
            )
            return _abstain_result(docs)

        try:
            system_prompt = await self._prompt_engine.render(
                self._system_prompt_name,
                assistant_name=self._assistant_name,
                product_name=self._product_name,
                current_date=today_iso(),
                tool_names=[],
            )
            answer_prompt = await self._prompt_engine.render(
                self._answer_prompt_name,
                question=question,
                chunks=[
                    {
                        "source": doc.source or doc.document_id,
                        "score": doc.score,
                        "content": doc.content,
                    }
                    for doc in docs
                ],
            )
            llm = self._llm_factory("rag")
            # Prior turns for context, with the current turn's raw question (always state["messages"][-1] here --
            # no earlier node touches messages) swapped for the RAG-grounded prompt instead of asking it twice.
            prior_turns = recent_history(state.get("messages", [])[:-1])
            # Custom writer, not the model's auto-stream: chat_stream.py's translator relies on this to avoid double-emitting.
            writer = stream_writer_or_noop()
            pieces: list[str] = []
            async for chunk in llm.astream(
                [
                    SystemMessage(content=system_prompt),
                    *prior_turns,
                    HumanMessage(content=answer_prompt),
                ]
            ):
                piece = content_to_text(chunk.content)
                if piece:
                    pieces.append(piece)
                    writer({"node": self.name, "text": piece})
            text = "".join(pieces)
            if not text:
                raise ValueError("rag: LLM stream produced no content")
            response: AIMessage = AIMessage(content=text)
        except Exception:
            logger.warning("rag.generation_failed", exc_info=True)
            return {
                "messages": [AIMessage(content=_FALLBACK_MESSAGE)],
                "answer": _FALLBACK_MESSAGE,
                "citations": [],
                "retrieved": [doc.model_dump(mode="json") for doc in docs],
                "abstained": False,
                "error": "rag_generation_failed",
            }

        citations = [
            {
                "index": index,
                "chunk_id": doc.id,
                "document_id": doc.document_id,
                "source": doc.source,
                "score": doc.score,
            }
            for index, doc in enumerate(docs, start=1)
        ]
        return {
            "messages": [response],
            "answer": text,
            "citations": citations,
            "retrieved": [doc.model_dump(mode="json") for doc in docs],
            "abstained": False,
        }


def _defer_result(*, error: str | None = None) -> dict[str, Any]:
    update: dict[str, Any] = {
        "messages": [AIMessage(content=_DEFER_MESSAGE)],
        "answer": _DEFER_MESSAGE,
        "citations": [],
        "retrieved": [],
        "abstained": True,
    }
    if error is not None:
        update["error"] = error
    return update


def _abstain_result(docs: list[RetrievalDoc]) -> dict[str, Any]:
    return {
        "messages": [AIMessage(content=_ABSTAIN_MESSAGE)],
        "answer": _ABSTAIN_MESSAGE,
        "citations": [],
        "retrieved": [doc.model_dump(mode="json") for doc in docs],
        "abstained": True,
    }
