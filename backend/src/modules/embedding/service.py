"""`OpenAIEmbeddingService` -- an OpenAI-compatible embeddings client (BLUEPRINT.md §3.8).

Same swap-point pattern as `agents/llm.py`'s `get_llm()`: point
`OPENAI_BASE_URL` at a self-hosted OpenAI-compatible embeddings endpoint
(vLLM or Text-Embeddings-Inference serving `EMBEDDING_MODEL`, default
`Qwen3-Embedding-0.6B`, Apache-2.0) or leave it blank to use OpenAI's own
hosted `text-embedding-3-small` as the opt-in alternative (§1's stack table,
§3.8). Either way, the rest of the codebase only ever depends on the
`EmbeddingService` Protocol below, never `langchain_openai.OpenAIEmbeddings`
directly.
"""

from __future__ import annotations

from typing import Protocol

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from core.config import settings
from core.errors.exceptions import ValidationAppError


class EmbeddingService(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbeddingService:
    """`EmbeddingService` backed by any OpenAI-compatible `/embeddings` endpoint."""

    def __init__(
        self,
        *,
        model: str = settings.EMBEDDING_MODEL,
        base_url: str = settings.OPENAI_BASE_URL,
        api_key: str = settings.OPENAI_API_KEY,
        dimension: int = settings.EMBEDDING_DIMENSION,
    ) -> None:
        self._dimension = dimension
        self._client = OpenAIEmbeddings(
            model=model,
            base_url=base_url or None,
            api_key=SecretStr(api_key or "not-needed-for-local-model"),
            # Self-hosted/non-OpenAI model names (e.g. `Qwen3-Embedding-0.6B`)
            # aren't in `tiktoken`'s registry, and this "safe length" pre-check
            # is only meaningful for OpenAI's own hosted models anyway --
            # disabling it means every request goes straight to the
            # configured endpoint instead of failing on a local tokenizer
            # lookup for a model tiktoken has never heard of.
            check_embedding_ctx_length=False,
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = await self._client.aembed_documents(texts)
        self._assert_dimension(vectors)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vector = await self._client.aembed_query(text)
        self._assert_dimension([vector])
        return vector

    def _assert_dimension(self, vectors: list[list[float]]) -> None:
        for vector in vectors:
            if len(vector) != self._dimension:
                raise ValidationAppError(
                    f"Embedding endpoint returned a {len(vector)}-dim vector, "
                    f"expected {self._dimension} (Settings.EMBEDDING_DIMENSION, "
                    "which must match the `chunks.embedding vector()` column "
                    "width). Check EMBEDDING_MODEL / EMBEDDING_DIMENSION agree "
                    "with what OPENAI_BASE_URL is actually serving."
                )
