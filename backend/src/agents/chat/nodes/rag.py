"""`rag` -- hybrid retrieve -> abstain-or-ground -> cite (BLUEPRINT.md §3.6, §3.8).

Retrieves via the injected `RetrievalService` (local fixture, pgvector
hybrid, or reranked -- all interchangeable behind the Protocol, §3.8),
abstains when the top (possibly reranked) result's score falls below
`config/behavior/retrieval.yaml`'s `abstain_score_threshold` -- calibrated,
not a bare `0.0` (§3.8) -- and otherwise grounds the answer in the retrieved
passages via `config/prompts/docs_assistant/answer.j2`'s numbered-citation
format, treating every retrieved passage as *context to cite*, never as
instructions to follow (OWASP LLM01's indirect-injection note, §3.12 --
retrieved text is untrusted).

**Streaming (§3.6, §3.7):** this is the template's worked example of a
"structured node" in the streaming-technique sense -- its answer is only
final once retrieval, abstention, and citation-numbering all land together,
so it pushes incremental text through LangGraph's custom stream writer
(`get_stream_writer()`) as it generates, rather than relying on
`on_chat_model_stream`/`stream_mode="messages"` the way the plain `answer`
node does. `modules/chat/chat_stream.py`'s translator knows to prefer this
node's custom-writer chunks over its (also-present, but redundant) raw model
stream.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.base import GraphNode
from agents.chat.nodes._protocols import BehaviorSource
from agents.chat.nodes._util import content_to_text, stream_writer_or_noop, today_iso
from agents.chat.state import ChatState
from agents.llm import get_llm
from agents.registry import register
from core.prompts.engine import PromptEngine
from modules.retrieval.protocol import RetrievalDoc, RetrievalService

logger = structlog.get_logger(__name__)

_DEFAULT_TOP_K = 5
_DEFAULT_ABSTAIN_THRESHOLD = 0.15
#: Reciprocal Rank Fusion is a rank-based fusion score, not a relevance
#: probability -- with `modules/retrieval/pgvector.py`'s default
#: `DEFAULT_RRF_K=60` it tops out around `2/61 ≈ 0.033`, so comparing it
#: against `_DEFAULT_ABSTAIN_THRESHOLD` (calibrated for a cross-encoder
#: reranker's ~[0, 1] score) would abstain on *every* query whenever
#: reranking is skipped or unavailable (`RERANK_ENABLED=false`, or
#: `RerankedRetrieval`'s no-reranker-configured/reranker-unreachable
#: fallback -- both documented, supported configurations, §3.8). RRF's rank
#: fusion carries no absolute-quality signal to calibrate a non-zero bar
#: against without a real per-corpus eval set (§3.11's retrieval eval is the
#: place to tune this) -- `0.0` only catches a genuinely empty candidate
#: set here, same as the `not docs` check just above it, so an unreranked
#: deployment answers from best-effort hybrid results instead of abstaining
#: unconditionally.
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
            # Fallback ladder (§3.6): "RAG-empty -> defer" also covers a
            # retrieval-layer failure (pgvector/embedding-service down) --
            # from the user's point of view it's the same "I don't have an
            # answer for that" outcome, not a hard turn failure.
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
            writer = stream_writer_or_noop()
            pieces: list[str] = []
            async for chunk in llm.astream(
                [SystemMessage(content=system_prompt), HumanMessage(content=answer_prompt)]
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
