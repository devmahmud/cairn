"""One forced-tool call producing {intent, confidence}; route.py (not this node) applies routing.yaml's confidence_threshold."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, cast

import structlog
from langchain_core.language_models import BaseChatModel

from agents.base import GraphNode
from agents.chat.nodes._protocols import BehaviorSource
from agents.chat.schemas import ClassifyResult
from agents.chat.state import ChatState
from agents.llm import get_llm
from agents.registry import register
from core.config import settings
from core.prompts.engine import PromptEngine

logger = structlog.get_logger(__name__)

_FALLBACK_INTENT = "unclear"
_STRUCTURED_OUTPUT_METHODS = frozenset({"json_schema", "json_mode", "function_calling"})


@register
class ClassifyNode(GraphNode[ChatState]):
    name = "classify"

    def __init__(
        self,
        *,
        prompt_engine: PromptEngine,
        behavior_config: BehaviorSource,
        llm_factory: Callable[[str], BaseChatModel] = get_llm,
        prompt_name: str = "docs_assistant/classify.j2",
    ) -> None:
        self._prompt_engine = prompt_engine
        self._behavior_config = behavior_config
        self._llm_factory = llm_factory
        self._prompt_name = prompt_name

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        question = state.get("input", "")
        try:
            routing = await self._behavior_config.get("routing")
            prompt = await self._prompt_engine.render(
                self._prompt_name, intents=routing.get("intents", []), question=question
            )
            llm = self._llm_factory("classify")
            structured_llm = llm.with_structured_output(
                ClassifyResult, method=_structured_output_method()
            )
            result = await structured_llm.ainvoke(prompt)
        except Exception:
            # Any classify-time failure (timeout, provider error, a momentarily-unparseable routing.yaml) degrades to "unclear", not a failed turn.
            logger.warning("classify.failed_falling_back_to_unclear", exc_info=True)
            return _fallback_result()

        if not isinstance(result, ClassifyResult):
            logger.warning("classify.unexpected_result_type", result_type=type(result).__name__)
            return _fallback_result()

        return {"intent": result.intent, "confidence": result.confidence}


def _fallback_result() -> dict[str, Any]:
    return {"intent": _FALLBACK_INTENT, "confidence": 0.0, "error": "classify_failed"}


def _structured_output_method() -> Literal["json_schema", "json_mode", "function_calling"]:
    mode = settings.STRUCTURED_OUTPUT_MODE
    if mode in _STRUCTURED_OUTPUT_METHODS:
        return cast(Literal["json_schema", "json_mode", "function_calling"], mode)
    # "guided_json" (vLLM grammar-constrained decoding) is provider-specific request kwargs, not a with_structured_output method.
    logger.warning(
        "classify.unsupported_structured_output_mode_falling_back",
        configured=mode,
        using="function_calling",
    )
    return "function_calling"
