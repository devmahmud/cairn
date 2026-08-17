"""Assembles the chat graph (BLUEPRINT.md §3.6, §8 step 5).

```
START -> input_rail -> classify -> route -+-> answer     -+
                                           +-> rag         +-> output_rail -> END
                                           +-> tool         |
                                           +-> guardrail   -+
```

Compiled **with the checkpointer** (`checkpointer=`, §3.3) so every node's
completion is a durable step (a crash mid-graph resumes from the last
completed node on the next call with the same `thread_id`, not from turn
zero). Two more pieces of that durability contract live here, not in any
one node:

- **`RetryPolicy` on the LLM/tool-calling nodes** (`classify`/`answer`/
  `rag`/`tool`) -- a different guarantee than checkpoint/resume: "this
  node's call failed, retry within the same run" vs. "the process died,
  pick up on the next request" (§3.6). Both matter; neither substitutes for
  the other.
- **Per-node `timeout=`** -- a graph-level backstop *above* each node's own
  per-role timeout (`agents/config.py`'s `RoleConfig.timeout`, enforced by
  `get_llm()`'s `ChatOpenAI(timeout=...)`). The node's own fallback ladder
  (§3.6) is expected to catch its role timeout first and degrade
  gracefully; this outer timeout only fires if that somehow doesn't happen
  (a hung call the client-side timeout didn't catch, a slow tool loop).

`durability="sync"` and the `TURN_BUDGET_SECONDS` wall-clock budget are
applied by the caller (`ChatAgent.ainvoke`, `agents/chat/agent.py`), not
here -- they're properties of *running* the compiled graph, not of its
structure.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from agents.chat.nodes._protocols import BehaviorSource
from agents.chat.nodes.answer import AnswerNode
from agents.chat.nodes.classify import ClassifyNode
from agents.chat.nodes.guardrail import GuardrailNode
from agents.chat.nodes.input_rail import InputRailNode
from agents.chat.nodes.output_rail import OutputRailNode
from agents.chat.nodes.rag import RagNode
from agents.chat.nodes.route import VALID_ROUTES, RouteNode
from agents.chat.nodes.tool import ToolAgentNode
from agents.chat.state import ChatState
from agents.llm import get_llm
from core.config import Settings, settings
from core.prompts.engine import PromptEngine
from modules.retrieval.protocol import RetrievalService

# One retry within the same run, on top of `get_llm()`'s own
# `max_retries=3` client-side retry (§3.6: a node-level retry and a
# client-level retry are different layers of the same "transient failure"
# problem -- the client retry covers one HTTP call, this covers the whole
# node, including e.g. a structured-output parse failure after a
# successful call).
_LLM_NODE_RETRY_POLICY = RetryPolicy(max_attempts=3)


def build_chat_graph(
    *,
    prompt_engine: PromptEngine,
    retrieval_service: RetrievalService,
    behavior_config: BehaviorSource,
    checkpointer: BaseCheckpointSaver | None,
    llm_factory: Callable[[str], BaseChatModel] = get_llm,
    app_settings: Settings = settings,
) -> CompiledStateGraph[ChatState, None, ChatState, ChatState]:
    graph = StateGraph(ChatState)

    graph.add_node(
        "input_rail",
        InputRailNode(behavior_config=behavior_config, app_settings=app_settings),
        timeout=5.0,
    )
    graph.add_node(
        "classify",
        ClassifyNode(
            prompt_engine=prompt_engine, behavior_config=behavior_config, llm_factory=llm_factory
        ),
        retry_policy=_LLM_NODE_RETRY_POLICY,
        timeout=15.0,
    )
    graph.add_node("route", RouteNode(behavior_config=behavior_config), timeout=5.0)
    graph.add_node(
        "answer",
        AnswerNode(prompt_engine=prompt_engine, llm_factory=llm_factory),
        retry_policy=_LLM_NODE_RETRY_POLICY,
        timeout=45.0,
    )
    graph.add_node(
        "rag",
        RagNode(
            prompt_engine=prompt_engine,
            retrieval_service=retrieval_service,
            behavior_config=behavior_config,
            llm_factory=llm_factory,
        ),
        retry_policy=_LLM_NODE_RETRY_POLICY,
        timeout=60.0,
    )
    graph.add_node(
        "tool",
        ToolAgentNode(llm_factory=llm_factory, max_hops=app_settings.MAX_GRAPH_HOPS),
        retry_policy=_LLM_NODE_RETRY_POLICY,
        # The tool node's own bounded loop can span several LLM + tool round
        # trips (up to `MAX_GRAPH_HOPS`); bound it by the same wall-clock
        # budget the whole turn gets rather than a tighter node-specific
        # number -- `ChatAgent.ainvoke`'s `TURN_BUDGET_SECONDS` wrapper is
        # the real backstop either way.
        timeout=app_settings.TURN_BUDGET_SECONDS,
    )
    graph.add_node("guardrail", GuardrailNode(), timeout=5.0)
    graph.add_node(
        "output_rail",
        OutputRailNode(behavior_config=behavior_config, app_settings=app_settings),
        timeout=5.0,
    )

    graph.add_edge(START, "input_rail")
    graph.add_edge("input_rail", "classify")
    graph.add_edge("classify", "route")
    graph.add_conditional_edges(
        "route",
        _select_branch,
        {branch: branch for branch in VALID_ROUTES},
    )
    for branch in VALID_ROUTES:
        graph.add_edge(branch, "output_rail")
    graph.add_edge("output_rail", END)

    return graph.compile(checkpointer=checkpointer)


def _select_branch(state: ChatState) -> str:
    route = state.get("route")
    # `route` (the node) only ever sets one of `VALID_ROUTES` -- this is a
    # defensive fallback for a state built by hand (a test, a resumed
    # checkpoint from an older graph version), not a path the graph itself
    # takes in normal operation.
    return route if route in VALID_ROUTES else "rag"
