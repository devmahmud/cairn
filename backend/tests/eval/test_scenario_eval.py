"""Scenario eval -- LLM-judged conversation quality (BLUEPRINT.md §3.11, §8 step 10).

Marked `eval` (`pyproject.toml`'s `addopts = "-m 'not eval'"` excludes this
from a plain `pytest` run and from `eval-gate.yml`'s CI gate -- §3.11:
"Cost-incurring LLM-judge eval stays manual"). Run it explicitly with real
LLM credentials configured:

    OPENAI_API_KEY=sk-... uv run pytest tests/eval -m eval -v -k scenario

Each scenario drives one turn through a real `ChatAgent`
(`tests/eval/support.py`) against the same fixture docs corpus used offline
elsewhere in this repo (`modules/retrieval/fixture.py`'s "Lumen" example
product), then asks a second LLM call (`tests/eval/judge.py`) to score the
answer 1-5 against a short rubric -- not an exact-match assertion, since a
real model's phrasing varies run to run; the judge is what makes this an
*eval*, not a unit test.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from tests.eval.judge import judge_answer
from tests.eval.support import build_eval_chat_agent, require_live_llm

pytestmark = pytest.mark.eval


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    text: str
    rubric: str
    min_score: int = 3


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="greeting",
        text="Hey there!",
        rubric=(
            "A short, friendly greeting back that invites the user to ask a "
            "question. Must not invent any product facts -- there's nothing to "
            "ground yet."
        ),
    ),
    Scenario(
        name="grounded_auth_question",
        text="How do I authenticate my API requests?",
        rubric=(
            "Should explain sending an API key as a bearer token in the "
            "Authorization header, matching the docs, and include at least one "
            "inline citation like [1]."
        ),
        min_score=4,
    ),
    Scenario(
        name="grounded_rate_limit_question",
        text="What happens when I exceed the rate limit?",
        rubric=(
            "Should mention an HTTP 429 response and a Retry-After header, "
            "matching the docs, with a citation."
        ),
        min_score=4,
    ),
    Scenario(
        name="grounded_webhook_retry_question",
        text=(
            "How many times will a failed webhook delivery be retried, and "
            "what's the backoff strategy?"
        ),
        rubric=(
            "Should say five retries with exponential backoff, matching the docs, with a citation."
        ),
        min_score=4,
    ),
    Scenario(
        name="out_of_scope_abstains_instead_of_fabricating",
        text="What's your refund policy for annual subscriptions?",
        rubric=(
            "Must NOT invent a refund policy or any specific figures -- the "
            "docs corpus has no billing/refund content. Should say this isn't "
            "covered and suggest rephrasing or asking something else."
        ),
    ),
    Scenario(
        name="ambiguous_input_asks_for_clarification",
        text="hmm not sure, maybe?",
        rubric=(
            "Should ask a clarifying question or invite the user to rephrase, "
            "rather than guessing at an unrelated topic or fabricating an answer."
        ),
    ),
    Scenario(
        name="web_search_intent_explains_the_gap_honestly",
        text="What's the latest version of the API released this week?",
        rubric=(
            "Should explain that live web search / current information isn't "
            "available in this deployment, without fabricating a version number "
            "or release date."
        ),
    ),
)


@pytest.fixture(autouse=True)
def _require_live_llm() -> None:
    require_live_llm()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
async def test_scenario_meets_the_judge_rubric(scenario: Scenario) -> None:
    agent = build_eval_chat_agent()

    result = await agent.ainvoke(conversation_id=uuid4(), user_id=None, text=scenario.text)
    answer = result.get("answer") or ""
    assert answer, f"{scenario.name}: turn produced no answer at all -- {result}"

    verdict = await judge_answer(question=scenario.text, answer=answer, rubric=scenario.rubric)

    assert verdict.score >= scenario.min_score, (
        f"{scenario.name}: judge scored {verdict.score}/5 (< {scenario.min_score}) -- "
        f"{verdict.reasoning}\nAnswer was: {answer!r}"
    )
