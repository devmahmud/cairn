"""split_into_sections splits on ## headings (one parent per section); chunk_text token-splits within each so child chunks share a parent_id for reranker dedup."""

from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE_TOKENS = 512
CHUNK_OVERLAP_TOKENS = round(CHUNK_SIZE_TOKENS * 0.15)
# Used only to measure chunk size, not to call a model -- a reasonable token-count proxy regardless of which model EMBEDDING_MODEL actually is.
TIKTOKEN_ENCODING = "cl100k_base"

_SECTION_SPLIT_RE = re.compile(r"(?=^##\s)", re.MULTILINE)


def split_into_sections(text: str) -> list[str]:
    """A document with no ## headings is treated as one section -- every chunk shares a single parent_id."""
    sections = [section.strip() for section in _SECTION_SPLIT_RE.split(text) if section.strip()]
    return sections or ([text.strip()] if text.strip() else [])


def build_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=TIKTOKEN_ENCODING,
        chunk_size=CHUNK_SIZE_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
    )


def chunk_text(text: str) -> list[str]:
    return build_splitter().split_text(text)
