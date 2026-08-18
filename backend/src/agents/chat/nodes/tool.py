"""tool: bounded, hop-capped tool-calling loop. LangGraph checkpoints per node, not per tool call -- a real side-effecting tool needs its own idempotency key, not "the checkpointer already ran this node" as dedup."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.tools import BaseTool, tool

from agents.base import GraphNode
from agents.chat.nodes._util import content_to_text, stream_writer_or_noop, today_iso
from agents.chat.state import ChatState
from agents.llm import get_llm
from agents.registry import register
from core.config import settings

logger = structlog.get_logger(__name__)

_FALLBACK_MESSAGE = "Sorry, I ran into a problem using a tool to answer that. Please try again."

_TOOL_SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. Use them only when "
    "the user's question genuinely needs them; otherwise answer directly. "
    "Today's date is {today}."
)


@tool
def get_current_date() -> str:
    """Return today's date as an ISO-8601 string (e.g. '2026-08-17')."""
    return today_iso()


@tool
def web_search(query: str) -> str:
    """Search the web for current information not covered by the docs corpus."""
    # Stub, not a real integration: this template ships with zero required external API keys.
    return (
        f"Web search is not configured in this deployment (query was: {query!r}). "
        "Tell the user this question needs current information you don't have "
        "access to yet."
    )


_DEFAULT_TOOLS: tuple[BaseTool, ...] = (get_current_date, web_search)


@register
class ToolAgentNode(GraphNode[ChatState]):
    name = "tool"

    def __init__(
        self,
        *,
        llm_factory: Callable[[str], BaseChatModel] = get_llm,
        max_hops: int = settings.MAX_GRAPH_HOPS,
        tools: Sequence[BaseTool] = _DEFAULT_TOOLS,
    ) -> None:
        self._llm_factory = llm_factory
        self._max_hops = max_hops
        self._tools = list(tools)
        self._tools_by_name = {t.name: t for t in self._tools}

    async def __call__(self, state: ChatState) -> dict[str, Any]:
        question = state.get("input", "")
        messages: list[BaseMessage] = [
            SystemMessage(content=_TOOL_SYSTEM_PROMPT.format(today=today_iso())),
            HumanMessage(content=question),
        ]
        bound_llm = self._llm_factory("tool").bind_tools(self._tools)
        writer = stream_writer_or_noop()

        hops = 0
        try:
            while True:
                response = await bound_llm.ainvoke(messages)
                messages.append(response)

                if not response.tool_calls:
                    # No writer call here: this turn auto-streams via stream_mode="messages" like answer.py's node does.
                    text = content_to_text(response.content)
                    return {"messages": [response], "answer": text, "citations": [], "hops": hops}

                hops += 1
                if hops > self._max_hops:
                    logger.warning(
                        "tool.hop_cap_exceeded", max_hops=self._max_hops, question=question
                    )
                    return _graceful_result(hops, error="tool_hop_cap_exceeded")

                for call in response.tool_calls:
                    messages.append(await self._invoke_one(call, writer))
        except Exception:
            # Catches failures outside a single tool call; a tool's own failure is handled inside _invoke_one instead.
            logger.warning("tool.failed_falling_back_to_graceful_message", exc_info=True)
            return _graceful_result(hops, error="tool_error")

    async def _invoke_one(
        self, call: ToolCall, writer: Callable[[dict[str, Any]], None]
    ) -> BaseMessage:
        name = call["name"]
        matched_tool = self._tools_by_name.get(name)
        if matched_tool is None:
            message: BaseMessage = ToolMessage(
                content=f"Unknown tool {name!r}.", tool_call_id=call["id"]
            )
            writer(
                {
                    "node": self.name,
                    "type": "tool_result",
                    "tool_name": name,
                    "result": message.content,
                }
            )
            return message
        try:
            # Passing the full ToolCall, not just call["args"], makes ainvoke return a ready ToolMessage stamped with tool_call_id.
            result = await matched_tool.ainvoke(call)
        except Exception as exc:
            logger.warning("tool.tool_call_failed", tool_name=name, exc_info=True)
            message = ToolMessage(content=f"Tool {name!r} failed: {exc}", tool_call_id=call["id"])
            writer(
                {
                    "node": self.name,
                    "type": "tool_result",
                    "tool_name": name,
                    "result": message.content,
                }
            )
            return message

        message = result if isinstance(result, BaseMessage) else _wrap_result(result, call)
        writer(
            {
                "node": self.name,
                "type": "tool_result",
                "tool_name": name,
                "result": content_to_text(message.content),
            }
        )
        return message


def _wrap_result(result: Any, call: ToolCall) -> BaseMessage:
    return ToolMessage(content=str(result), tool_call_id=call["id"])


def _graceful_result(hops: int, *, error: str) -> dict[str, Any]:
    return {
        "messages": [AIMessage(content=_FALLBACK_MESSAGE)],
        "answer": _FALLBACK_MESSAGE,
        "citations": [],
        "hops": hops,
        "error": error,
    }
