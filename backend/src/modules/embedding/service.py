"""Same swap-point pattern as agents/llm.py -- point OPENAI_BASE_URL at a self-hosted embeddings endpoint, or leave blank for OpenAI's hosted API."""

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
            # Self-hosted model names (e.g. Qwen3-Embedding-0.6B) aren't in tiktoken's registry -- disabling this pre-check avoids a lookup failure.
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
