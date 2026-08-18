"""Unit tests for `agents.chat.nodes.rag.RagNode` (BLUEPRINT.md §3.6, §3.8).

Covers the three-way branch the node's docstring promises: ground (ordinary
grounded answer with citations), abstain (top score below
`abstain_score_threshold`), and defer (no results at all, or the retrieval
layer itself failing) -- the "RAG-empty -> defer" fallback-ladder entry.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from agents.chat.nodes.rag import RagNode
from agents.chat.state import ChatState
from core.prompts.engine import PromptEngine
from core.prompts.loader import FileSystemJ2Loader
from modules.retrieval.protocol import RetrievalDoc
from tests.unit.fakes import FakeChatModel


class _FakeBehaviorConfig:
    def __init__(
        self,
        *,
        top_k: int = 5,
        abstain_score_threshold: float = 0.15,
        abstain_score_threshold_unreranked: float = 0.0,
    ) -> None:
        self._cfg = {
            "top_k": top_k,
            "abstain_score_threshold": abstain_score_threshold,
            "abstain_score_threshold_unreranked": abstain_score_threshold_unreranked,
        }

    async def get(self, name: str) -> dict[str, Any]:
        assert name == "retrieval"
        return self._cfg


class _FakeRetrievalService:
    def __init__(self, docs: list[RetrievalDoc] | Exception) -> None:
        self._docs = docs

    async def query(
        self, text: str, top_k: int, filters: dict[str, Any] | None = None
    ) -> list[RetrievalDoc]:
        if isinstance(self._docs, Exception):
            raise self._docs
        return self._docs


_PROMPT_ENGINE = PromptEngine(loader=FileSystemJ2Loader(base_path="config/prompts"))
_DOC = RetrievalDoc(
    id="chunk-1",
    document_id="doc-1",
    content="Send an Authorization header.",
    source="auth.md",
    score=0.8,
)


def _node(
    *,
    docs: list[RetrievalDoc] | Exception,
    llm: FakeChatModel | None = None,
    behavior_config: _FakeBehaviorConfig | None = None,
) -> RagNode:
    def llm_factory(role: str) -> FakeChatModel:
        assert role == "rag"
        assert llm is not None, "generation should not be attempted for this scenario"
        return llm

    return RagNode(
        prompt_engine=_PROMPT_ENGINE,
        retrieval_service=_FakeRetrievalService(docs),
        behavior_config=behavior_config or _FakeBehaviorConfig(),
        llm_factory=llm_factory,
    )


def _state(question: str = "How do I authenticate?") -> ChatState:
    return {"input": question}


async def test_grounds_answer_with_citations_when_top_score_is_high() -> None:
    node = _node(
        docs=[_DOC], llm=FakeChatModel(responses=[AIMessage(content="Use a bearer token [1].")])
    )

    result = await node(_state())

    assert result["abstained"] is False
    assert result["answer"] == "Use a bearer token [1]."
    assert result["citations"] == [
        {
            "index": 1,
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "source": "auth.md",
            "score": 0.8,
        }
    ]
    assert len(result["retrieved"]) == 1


async def test_abstains_when_top_score_is_below_threshold() -> None:
    weak_doc = _DOC.model_copy(update={"score": 0.02})
    node = _node(docs=[weak_doc])  # no LLM configured -- generation must not run

    result = await node(_state())

    assert result["abstained"] is True
    assert result["citations"] == []
    assert len(result["retrieved"]) == 1  # kept for debugging/audit, just not cited


async def test_defers_when_no_documents_are_retrieved() -> None:
    node = _node(docs=[])

    result = await node(_state())

    assert result["abstained"] is True
    assert result["retrieved"] == []
    assert "error" not in result


async def test_defers_with_error_code_when_retrieval_raises() -> None:
    node = _node(docs=RuntimeError("pgvector is down"))

    result = await node(_state())

    assert result["abstained"] is True
    assert result["error"] == "rag_retrieval_failed"


# --- Unreranked (RRF-scale) scores use their own threshold, not the
# reranker-calibrated one (regression coverage for the bug where every
# unreranked query abstained unconditionally: `PgVectorHybridRetrievalService`'s
# bare RRF score, `k=60`, tops out around `2/61 ≈ 0.033` -- always below the
# reranker-scale `0.15` default). Uses that real RRF magnitude, not a
# hand-picked reranker-scale number like `_DOC`'s `0.8` above, so this
# regresses loudly if the two scales ever get compared against each other
# again. ------------------------------------------------------------------

_UNRERANKED_DOC = _DOC.model_copy(update={"score": 2.0 / 61.0, "score_is_calibrated": False})


async def test_grounds_answer_on_a_realistic_unreranked_rrf_score() -> None:
    """A top-of-both-lists RRF score (~0.033) is nowhere near the
    reranker-scale `0.15` default -- comparing it against that threshold
    would abstain here. It must ground instead."""
    node = _node(
        docs=[_UNRERANKED_DOC],
        llm=FakeChatModel(responses=[AIMessage(content="Use a bearer token [1].")]),
    )

    result = await node(_state())

    assert result["abstained"] is False
    assert result["answer"] == "Use a bearer token [1]."


async def test_abstains_on_unreranked_score_below_the_unreranked_threshold() -> None:
    """The unreranked threshold is independently configurable and honored,
    same as the reranked-scale one already is."""
    weak_doc = _UNRERANKED_DOC.model_copy(update={"score": 0.01})
    node = _node(
        docs=[weak_doc],
        behavior_config=_FakeBehaviorConfig(abstain_score_threshold_unreranked=0.02),
    )

    result = await node(_state())

    assert result["abstained"] is True
