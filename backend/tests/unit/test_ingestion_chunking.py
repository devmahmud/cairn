"""Unit tests for `modules.ingestion.chunking` (BLUEPRINT.md §3.8)."""

from __future__ import annotations

from modules.ingestion.chunking import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_SIZE_TOKENS,
    chunk_text,
    split_into_sections,
)


def test_split_into_sections_splits_on_top_level_headings() -> None:
    text = "# Title\nintro text\n\n## One\nfirst body\n\n## Two\nsecond body\n"

    sections = split_into_sections(text)

    # Content before the first `##` heading (here, the `# Title` + intro)
    # becomes its own leading section too -- it has no `##` heading of its
    # own to attach to.
    assert len(sections) == 3
    assert sections[0].startswith("# Title")
    assert sections[1].startswith("## One")
    assert sections[2].startswith("## Two")


def test_split_into_sections_with_no_headings_returns_one_section() -> None:
    sections = split_into_sections("just a paragraph, no headings at all.")

    assert sections == ["just a paragraph, no headings at all."]


def test_split_into_sections_on_blank_text_returns_no_sections() -> None:
    assert split_into_sections("   \n  ") == []


def test_chunk_size_and_overlap_match_blueprint_defaults() -> None:
    assert CHUNK_SIZE_TOKENS == 512
    assert round(512 * 0.15) == CHUNK_OVERLAP_TOKENS


def test_chunk_text_splits_long_text_into_multiple_chunks() -> None:
    long_text = "This is one sentence about the product. " * 200

    chunks = chunk_text(long_text)

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


def test_chunk_text_returns_short_text_as_a_single_chunk() -> None:
    chunks = chunk_text("A short paragraph that fits in one chunk easily.")

    assert len(chunks) == 1
