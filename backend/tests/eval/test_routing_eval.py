"""Classification/routing eval -- confusion matrix over `routing.yaml`'s
intents (BLUEPRINT.md §3.6, §3.11, §8 step 10: "the make-or-break for a router").

Marked `eval` for the same reason `test_scenario_eval.py` is:
`agents.chat.nodes.classify.ClassifyNode` always calls a real LLM
(`agents/llm.py`'s `get_llm`), so scoring it against labeled utterances is
cost-incurring the same way a judged conversation scenario is (§3.11:
"Cost-incurring LLM-judge eval stays manual"). `agents.chat.nodes.route.RouteNode`'s
own deterministic mapping is already covered offline, with zero LLM
involved, by `tests/unit/test_route_node.py` -- this file is the other half:
does the *classifier* actually pick the right intent for a labeled utterance
in the first place, and does that intent then route where `routing.yaml`
says it should.

Run explicitly:

    OPENAI_API_KEY=sk-... uv run pytest tests/eval -m eval -v -k routing
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import cast

import pytest

from agents.chat.nodes.classify import ClassifyNode
from agents.chat.nodes.route import RouteNode
from agents.chat.state import ChatState
from agents.llm import get_llm
from tests.eval.support import (
    build_eval_behavior_config,
    build_eval_prompt_engine,
    require_live_llm,
)

pytestmark = pytest.mark.eval


@dataclass(frozen=True, slots=True)
class LabeledUtterance:
    text: str
    expected_intent: str


# Covers every intent `config/behavior/routing.yaml` defines for the
# docs-assistant example -- generic phrasing, unrelated to any real product.
LABELED_UTTERANCES: tuple[LabeledUtterance, ...] = (
    LabeledUtterance("How do I authenticate my requests to the API?", "product_question"),
    LabeledUtterance("What's the rate limit per minute on my API key?", "product_question"),
    LabeledUtterance("How do I configure a webhook for note.created events?", "product_question"),
    LabeledUtterance("What does the 401 Unauthorized error code mean?", "product_question"),
    LabeledUtterance("Hi there!", "greeting"),
    LabeledUtterance("Hello, how are you doing today?", "greeting"),
    LabeledUtterance("Good morning!", "greeting"),
    LabeledUtterance("What's the latest version of the API released this week?", "web_search"),
    LabeledUtterance(
        "Can you check today's pricing for the pro plan on your website?", "web_search"
    ),
    LabeledUtterance("Is there an outage happening with your service right now?", "web_search"),
    LabeledUtterance("What was the previous question I asked you?", "meta_conversation"),
    LabeledUtterance("Can you summarize what we've talked about so far?", "meta_conversation"),
    LabeledUtterance("What did you just tell me?", "meta_conversation"),
    LabeledUtterance("asdkjasdlkj qwoieqwoie", "unclear"),
    LabeledUtterance("???", "unclear"),
    LabeledUtterance("banana purple seventeen maybe", "unclear"),
)

# Real-model classification has some irreducible run-to-run variance even at
# temperature=0.0 across providers/model versions -- these thresholds catch
# a genuinely regressed classifier/prompt, not every imperfect call.
_MIN_INTENT_ACCURACY = 0.7
_MIN_ROUTE_ACCURACY = 0.7


@pytest.fixture(autouse=True)
def _require_live_llm() -> None:
    require_live_llm()


async def test_classify_confusion_matrix_and_routed_outcome() -> None:
    behavior_config = build_eval_behavior_config()
    classify_node = ClassifyNode(
        prompt_engine=build_eval_prompt_engine(),
        behavior_config=behavior_config,
        llm_factory=get_llm,
    )
    route_node = RouteNode(behavior_config=behavior_config)
    routing_cfg = await behavior_config.get("routing")
    expected_route_by_intent = {
        entry["name"]: entry["route"]
        for entry in routing_cfg.get("intents", [])
        if entry.get("name")
    }

    confusion: Counter[tuple[str, str]] = Counter()
    route_correct = 0
    report_lines: list[str] = []

    for case in LABELED_UTTERANCES:
        classify_result = await classify_node(cast(ChatState, {"input": case.text}))
        predicted_intent = classify_result["intent"]
        confusion[(case.expected_intent, predicted_intent)] += 1

        route_result = await route_node(cast(ChatState, classify_result))
        expected_route = expected_route_by_intent.get(case.expected_intent, "rag")
        route_ok = route_result["route"] == expected_route
        route_correct += int(route_ok)

        report_lines.append(
            f"  {case.text!r} expected={case.expected_intent!r} "
            f"predicted={predicted_intent!r} confidence={classify_result.get('confidence')} "
            f"route={route_result['route']!r} expected_route={expected_route!r} "
            f"{'OK' if route_ok else 'MISROUTED'}"
        )

    total = len(LABELED_UTTERANCES)
    intent_correct = sum(
        count for (expected, predicted), count in confusion.items() if expected == predicted
    )
    intent_accuracy = intent_correct / total
    route_accuracy = route_correct / total
    report = "\n".join(report_lines)

    assert intent_accuracy >= _MIN_INTENT_ACCURACY, (
        f"classify intent accuracy {intent_accuracy:.0%} < {_MIN_INTENT_ACCURACY:.0%}\n{report}"
    )
    assert route_accuracy >= _MIN_ROUTE_ACCURACY, (
        f"routed-outcome accuracy {route_accuracy:.0%} < {_MIN_ROUTE_ACCURACY:.0%}\n{report}"
    )
