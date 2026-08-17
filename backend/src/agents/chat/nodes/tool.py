"""`tool` -- a bounded tool-calling loop, hop-capped via `MAX_GRAPH_HOPS` (BLUEPRINT.md §3.6).

`route` sends turns here for the `web_search` intent (per
`config/behavior/routing.yaml`) -- questions the docs corpus can't answer.
This template ships no real external tool integration (no API key should be
required to boot, design principle #4): `web_search` below is a stub that
explains it isn't configured rather than making a network call, and
`get_current_date` is a harmless, genuinely useful example of a real local
tool. Both demonstrate the loop's shape; swap in real tools by passing
`tools=[...]` to the constructor (the DI-wired instance in
`agents/chat/graph.py` is the one place that needs to change).

**Idempotency (§3.6's durability contract):** a process crash between a
tool's side effect landing and the graph's checkpoint write means a resume
re-executes this *entire node* -- LangGraph checkpoints per node, not per
tool call within one node. Both bundled tools are naturally idempotent
(pure functions of their arguments, no external mutation), which is exactly
what makes that safe here. A tool with a real side effect (a write to a
third-party API) would need its own idempotency key threaded through the
call args instead -- don't rely on "the checkpointer already ran this node"
as the dedup mechanism, because the crash window above is exactly the case
where it hasn't (see this node's own bounded loop below for where that key
would be threaded through).

**Streaming (§3.6, §3.7):** the LLM turns that decide *whether* to call a
tool are forced-tool-bound (`bind_tools`) -- their `on_chat_model_stream`
chunks carry only tool-call argument deltas, not user-facing text, so this
node doesn't try to stream those. It does push one `tool_result` event per
completed call via `get_stream_writer()` so the client can show "ran
`web_search`" as it happens rather than only after the whole bounded loop
finishes; the loop's *final* plain-text turn (no more tool calls) still
auto-streams through `stream_mode="messages"` like `answer.py`'s does, since
by then the model isn't emitting tool-call chunks.
"""

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
    # A stand-in, not a real integration: this template ships with zero
    # required external API keys (design principle #4). A real deployment
    # wires an actual search provider here -- the tool-calling loop below
    # doesn't change either way.
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
            # Fallback ladder (§3.6: "tool-error -> graceful message") --
            # catches failures outside a single tool call (the LLM call
            # itself, malformed tool-call arguments the model produced,
            # ...). A single tool's own failure is handled inside
            # `_invoke_one` instead, without aborting the loop.
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
            # Passing the full `ToolCall` (not just `call["args"]`) makes
            # `BaseTool.ainvoke` return a ready-made `ToolMessage` stamped
            # with the matching `tool_call_id` -- see this module's
            # docstring for the idempotency note that applies here for any
            # tool with a real side effect.
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
