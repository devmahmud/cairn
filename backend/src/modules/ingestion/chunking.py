"""Chunking for RAG ingestion (BLUEPRINT.md §3.8: "~512 tokens, ~15% overlap").

Two levels, deliberately: `split_into_sections` first splits a markdown
document on its top-level `##` headings -- each section becomes one
ingestion "parent" (`Chunk.parent_id`, §3.3/§3.8: "dedupe by `parent_id`").
`chunk_text` then applies the actual token-bounded splitter *within* each
section, so multiple overlapping child chunks from the same section share
one `parent_id` -- exactly what `modules/retrieval/reranker.py`'s
`RerankedRetrieval` dedupes on when a query's top results collapse onto the
same source passage.
"""

from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE_TOKENS = 512
# "~15% overlap" (§3.8), rounded to a whole token count.
CHUNK_OVERLAP_TOKENS = round(CHUNK_SIZE_TOKENS * 0.15)
# `cl100k_base` (the OpenAI/tiktoken encoding `RecursiveCharacterTextSplitter
# .from_tiktoken_encoder` defaults callers toward) is only ever used here to
# *measure* chunk size, not to call any model -- a reasonable, widely
# available proxy for token count regardless of which model actually serves
# `EMBEDDING_MODEL`.
TIKTOKEN_ENCODING = "cl100k_base"

_SECTION_SPLIT_RE = re.compile(r"(?=^##\s)", re.MULTILINE)


def split_into_sections(text: str) -> list[str]:
    """Split markdown `text` on top-level (`##`) headings.

    A document with no `##` headings at all is treated as one section --
    every chunk it produces shares a single `parent_id`.
    """
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
