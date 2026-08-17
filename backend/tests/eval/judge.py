"""LLM-judge scoring for the scenario eval (BLUEPRINT.md §3.11, §8 step 10).

Not a `test_*.py` file -- same "importable support module" pattern as
`tests/unit/fakes.py`/`tests/eval/support.py`. A real model's phrasing
varies run to run, so `test_scenario_eval.py` doesn't assert exact answer
text; instead a second model call scores the answer 1-5 against a short,
scenario-specific rubric -- the actual "judge" in "LLM-judged conversation
scenarios" (§3.11).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agents.llm import get_llm
from core.config import settings

_JUDGE_SYSTEM_PROMPT = (
    "You are an impartial evaluator for a documentation-assistant chat "
    "product. You will be given the user's question, the assistant's "
    "answer, and a short rubric describing what a good answer looks like "
    "for this question. Score the answer from 1 (fails the rubric badly, "
    "e.g. a fabricated fact or a hallucinated claim) to 5 (fully meets the "
    "rubric). Be strict about factual grounding -- an answer that invents "
    "something not supported by the rubric's expectations should score low "
    "even if it reads fluently."
)

_JUDGE_USER_TEMPLATE = "Question:\n{question}\n\nAssistant's answer:\n{answer}\n\nRubric:\n{rubric}"

# Mirrors `agents.chat.nodes.classify._structured_output_method` -- kept as
# a small, local duplicate rather than importing that (deliberately
# private) helper across an eval/production boundary.
_STRUCTURED_OUTPUT_METHODS = frozenset({"json_schema", "json_mode", "function_calling"})


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    reasoning: str


async def judge_answer(
    *,
    question: str,
    answer: str,
    rubric: str,
    llm_factory: Callable[[str], BaseChatModel] = get_llm,
) -> JudgeVerdict:
    llm = llm_factory("judge")
    structured_llm = llm.with_structured_output(JudgeVerdict, method=_structured_output_method())
    result = await structured_llm.ainvoke(
        [
            SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
            HumanMessage(
                content=_JUDGE_USER_TEMPLATE.format(question=question, answer=answer, rubric=rubric)
            ),
        ]
    )
    if not isinstance(result, JudgeVerdict):
        raise TypeError(f"Judge model returned {type(result).__name__}, expected JudgeVerdict.")
    return result


def _structured_output_method() -> Literal["json_schema", "json_mode", "function_calling"]:
    mode = settings.STRUCTURED_OUTPUT_MODE
    if mode in _STRUCTURED_OUTPUT_METHODS:
        return cast(Literal["json_schema", "json_mode", "function_calling"], mode)
    return "function_calling"
