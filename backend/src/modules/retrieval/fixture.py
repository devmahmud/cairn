"""Zero-dependency retrieval backing USE_LOCAL_RETRIEVAL=true -- bundled fixture corpus, deterministic keyword-overlap scoring, no embedding model or Postgres."""

from __future__ import annotations

import re
from dataclasses import dataclass

from modules.retrieval.protocol import RetrievalDoc

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Just enough to stop trivial words like "the"/"is" from spuriously overlapping every passage; real retrieval (FTS + reranker) doesn't need this.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    }
)


def _tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS}


@dataclass(frozen=True, slots=True)
class _FixturePassage:
    id: str
    document_id: str
    title: str
    content: str


_FIXTURE_PASSAGES: tuple[_FixturePassage, ...] = (
    _FixturePassage(
        id="lumen-getting-started-1",
        document_id="lumen-getting-started",
        title="Getting started with the Lumen API",
        content=(
            "To get started with the Lumen API, create an API key from the "
            "dashboard's Settings > API Keys page. Every request must include "
            "the key as a bearer token in the Authorization header: "
            "'Authorization: Bearer <your-api-key>'. The base URL for all "
            "requests is https://api.lumen.example/v1."
        ),
    ),
    _FixturePassage(
        id="lumen-auth-1",
        document_id="lumen-authentication",
        title="Authentication and key rotation",
        content=(
            "Lumen API keys never expire automatically, but you can rotate one "
            "at any time from the dashboard -- the old key keeps working for "
            "24 hours after rotation so in-flight deployments don't break. "
            "Requests with a missing or invalid Authorization header receive a "
            "401 Unauthorized response with an error code of 'invalid_api_key'."
        ),
    ),
    _FixturePassage(
        id="lumen-rate-limits-1",
        document_id="lumen-rate-limits",
        title="Rate limits",
        content=(
            "The Lumen API enforces a default rate limit of 120 requests per "
            "minute per API key. When you exceed it, the API responds with "
            "HTTP 429 and a Retry-After header indicating how many seconds to "
            "wait before retrying. Higher limits are available on request for "
            "verified production workloads."
        ),
    ),
    _FixturePassage(
        id="lumen-webhooks-1",
        document_id="lumen-webhooks",
        title="Webhooks",
        content=(
            "Lumen can notify your application of events -- note.created, "
            "note.updated, and task.completed -- via webhooks. Configure an "
            "endpoint URL under Settings > Webhooks; Lumen retries a failed "
            "delivery up to five times with exponential backoff before giving "
            "up and marking the webhook as failing in the dashboard."
        ),
    ),
    _FixturePassage(
        id="lumen-errors-1",
        document_id="lumen-errors",
        title="Error handling",
        content=(
            "Lumen API errors are JSON objects with `error.code` and "
            "`error.message` fields. Common codes: `invalid_api_key` (401), "
            "`rate_limited` (429), `not_found` (404), and `validation_error` "
            "(422) when a request body fails schema validation."
        ),
    ),
)


class LocalFixtureRetrievalService:
    """Keyword-overlap ratio scoring -- good enough to exercise rag-node logic offline, not real relevance ranking."""

    async def query(
        self, text: str, top_k: int, filters: dict[str, object] | None = None
    ) -> list[RetrievalDoc]:
        query_tokens = _tokenize(text)
        scored: list[tuple[float, _FixturePassage]] = []
        for passage in _FIXTURE_PASSAGES:
            score = _overlap_score(query_tokens, passage.content)
            if score > 0.0:
                scored.append((score, passage))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            RetrievalDoc(
                id=passage.id,
                document_id=passage.document_id,
                parent_id=None,
                content=passage.content,
                source=passage.title,
                score=score,
                metadata={"fixture": True},
            )
            for score, passage in scored[:top_k]
        ]


def _overlap_score(query_tokens: set[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = _tokenize(content)
    overlap = len(query_tokens & content_tokens)
    return overlap / len(query_tokens)
