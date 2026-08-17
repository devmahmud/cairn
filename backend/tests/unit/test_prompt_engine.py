"""Unit tests for `core.prompts.engine.PromptEngine` / `core.prompts.loader.FileSystemJ2Loader`
(BLUEPRINT.md §3.5, §8 step 4).

The first few tests render the real, bundled `config/prompts/docs_assistant/*.j2`
templates -- the startup-time sanity check the scaffold plan calls for: if
these fail, the shipped example prompts are broken, not just some
throwaway fixture. The rest exercise the two-tier resolution and the
explicit reload path against `tmp_path` fixtures (fixture-backed, no
network, per §3.11).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.errors.exceptions import NotFoundError
from core.prompts.engine import PromptEngine
from core.prompts.loader import FileSystemJ2Loader

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_PROMPTS_DIR = _BACKEND_ROOT / "config" / "prompts"


@pytest.fixture
def bundled_loader() -> FileSystemJ2Loader:
    return FileSystemJ2Loader(_BUNDLED_PROMPTS_DIR)


def test_bundled_system_prompt_renders(bundled_loader: FileSystemJ2Loader) -> None:
    rendered = bundled_loader.render(
        "docs_assistant/system.j2",
        assistant_name="Cairn Docs Bot",
        product_name="Cairn",
        current_date="2026-08-17",
        tool_names=["web_search"],
    )

    assert "Cairn Docs Bot" in rendered
    assert "Cairn documentation" in rendered
    assert "web_search" in rendered


def test_bundled_answer_prompt_renders_with_chunks(bundled_loader: FileSystemJ2Loader) -> None:
    rendered = bundled_loader.render(
        "docs_assistant/answer.j2",
        question="How do I configure retries?",
        chunks=[
            {
                "content": "Set max_retries on the client.",
                "source": "docs/retries.md",
                "score": 0.92,
            }
        ],
    )

    assert "How do I configure retries?" in rendered
    assert "[1]" in rendered
    assert "docs/retries.md" in rendered
    assert "0.92" in rendered


def test_bundled_answer_prompt_abstains_with_no_chunks(bundled_loader: FileSystemJ2Loader) -> None:
    rendered = bundled_loader.render(
        "docs_assistant/answer.j2", question="What's the meaning of life?", chunks=[]
    )

    assert "No documentation passages were retrieved" in rendered


def test_loader_raises_not_found_for_missing_template(bundled_loader: FileSystemJ2Loader) -> None:
    with pytest.raises(NotFoundError):
        bundled_loader.render("does_not_exist.j2")


def test_loader_reload_picks_up_edited_file(tmp_path: Path) -> None:
    prompt_path = tmp_path / "greeting.j2"
    prompt_path.write_text("Hello, {{ person }}!")
    loader = FileSystemJ2Loader(tmp_path)

    assert loader.render("greeting.j2", person="Ada") == "Hello, Ada!"

    prompt_path.write_text("Hi there, {{ person }}!")
    # `auto_reload=False` is deliberate (loader.py's docstring) -- without
    # an explicit `reload()`, the cached compiled template still wins.
    assert loader.render("greeting.j2", person="Ada") == "Hello, Ada!"

    loader.reload()
    assert loader.render("greeting.j2", person="Ada") == "Hi there, Ada!"


class _FakeLangfusePrompt:
    def __init__(self, text: str) -> None:
        self._text = text

    def compile(self, **kwargs: object) -> str:
        return self._text.format(**kwargs)


class _FakeLangfuseClient:
    def __init__(self, *, text: str | None = None, fail: bool = False) -> None:
        self._text = text
        self._fail = fail
        self.calls: list[tuple[str, str]] = []

    def get_prompt(self, name: str, *, label: str, type: str = "text") -> _FakeLangfusePrompt:
        self.calls.append((name, label))
        if self._fail:
            raise RuntimeError("Langfuse is unreachable")
        assert self._text is not None
        return _FakeLangfusePrompt(self._text)


async def test_prompt_engine_prefers_langfuse_when_enabled(tmp_path: Path) -> None:
    (tmp_path / "system.j2").write_text("bundled fallback for {{ person }}")
    loader = FileSystemJ2Loader(tmp_path)
    client = _FakeLangfuseClient(text="Hello from Langfuse, {person}!")
    engine = PromptEngine(
        loader, langfuse_client=client, langfuse_prompts_enabled=True, label="production"
    )

    rendered = await engine.render("system.j2", person="Ada")

    assert rendered == "Hello from Langfuse, Ada!"
    assert client.calls == [("system", "production")]


async def test_prompt_engine_falls_back_to_bundled_file_on_langfuse_failure(tmp_path: Path) -> None:
    (tmp_path / "system.j2").write_text("Bundled fallback, {{ person }}!")
    loader = FileSystemJ2Loader(tmp_path)
    client = _FakeLangfuseClient(fail=True)
    engine = PromptEngine(loader, langfuse_client=client, langfuse_prompts_enabled=True)

    rendered = await engine.render("system.j2", person="Ada")

    assert rendered == "Bundled fallback, Ada!"


async def test_prompt_engine_uses_bundled_file_when_langfuse_prompts_disabled(
    tmp_path: Path,
) -> None:
    (tmp_path / "system.j2").write_text("Bundled only, {{ person }}!")
    loader = FileSystemJ2Loader(tmp_path)
    client = _FakeLangfuseClient(text="should never be used")
    engine = PromptEngine(loader, langfuse_client=client, langfuse_prompts_enabled=False)

    rendered = await engine.render("system.j2", person="Ada")

    assert rendered == "Bundled only, Ada!"
    assert client.calls == []


async def test_prompt_engine_tolerates_enabled_flag_without_a_client(tmp_path: Path) -> None:
    (tmp_path / "system.j2").write_text("Bundled only, {{ person }}!")
    loader = FileSystemJ2Loader(tmp_path)
    engine = PromptEngine(loader, langfuse_client=None, langfuse_prompts_enabled=True)

    rendered = await engine.render("system.j2", person="Ada")

    assert rendered == "Bundled only, Ada!"
