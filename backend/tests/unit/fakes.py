"""A deterministic `BaseChatModel` test double shared by the offline chat-graph
tests (BLUEPRINT.md §8 step 5's acceptance check: "the graph should run
offline via a CLI or a unit test ... using a fake/stub LLM").

Not a `test_*.py` file -- pytest won't collect it as a test module, but
other files under `tests/unit/` import it as `tests.unit.fakes` (`tests/`
and every subdirectory carry an `__init__.py` for exactly this -- a stable,
package-qualified import path both `pytest` and `mypy` resolve the same
way, rather than relying on pytest's rootless-import sys.path insertion).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class _FakeStructuredRunnable(Runnable[Any, BaseModel]):
    """What `FakeChatModel.with_structured_output(...)` returns.

    Real chat models' structured-output Runnable parses the model's actual
    response into `schema`; this one just hands back whatever
    `structured_response` the test configured, ignoring the prompt --
    correct is scripted, not actually inferred, for a test double.
    """

    def __init__(self, response: BaseModel) -> None:
        self._response = response

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> BaseModel:
        return self._response


class FakeChatModel(BaseChatModel):
    """No network, no real provider -- `_generate` just pops a canned message.

    `responses` is consumed in call order across successive `.ainvoke()`
    calls, so a test can script a multi-turn exchange (e.g. the `tool`
    node's bounded loop: one `AIMessage` carrying `tool_calls`, then one
    without). `structured_response` is separate, consumed by
    `with_structured_output(...).ainvoke(...)` only.
    """

    responses: list[BaseMessage] = Field(default_factory=list)
    structured_response: BaseModel | None = None

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.responses:
            raise AssertionError("FakeChatModel: no more canned responses queued.")
        message = self.responses.pop(0)
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def bind_tools(  # type: ignore[override]
        self,
        tools: Sequence[BaseTool | dict[str, Any]],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> FakeChatModel:
        # The real `ChatOpenAI.bind_tools` narrows the schema the provider
        # is told about; this fake's canned `responses` already carry
        # whatever `tool_calls` a test wants, so binding is a no-op --
        # `self` already behaves like a tool-bound model.
        return self

    def with_structured_output(
        self, schema: Any = None, *, include_raw: bool = False, **kwargs: Any
    ) -> Runnable[Any, Any]:
        assert self.structured_response is not None, (
            "FakeChatModel.with_structured_output() called but no "
            "`structured_response` was configured on this fake."
        )
        return _FakeStructuredRunnable(self.structured_response)
