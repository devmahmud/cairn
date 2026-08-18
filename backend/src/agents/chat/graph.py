"""Assembles the chat graph: input_rail -> classify -> route -> {answer|rag|tool|guardrail} -> output_rail; compiled with the checkpointer so a crash mid-graph resumes from the last completed node, not turn zero."""

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

# On top of get_llm()'s own client-side max_retries=3 -- this covers the whole node (e.g. a parse failure after a successful call), not just one HTTP call.
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
        # Bound by the turn's own wall-clock budget, not a tighter node-specific number, since the loop can span several hops.
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
    # Defensive fallback for hand-built state (a test, an old checkpoint); the graph itself never takes this path.
    return route if route in VALID_ROUTES else "rag"
