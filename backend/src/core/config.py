"""Static, boot-time settings (BLUEPRINT.md §3.2, tier 1 of 3).

Loaded once from `.env` via `pydantic-settings` and immutable for the life of
the process. Tier 2 (runtime overrides, `config_overrides` table) lives in
`core/runtime_config.py`; tier 3 (prompts/behavior file hot reload) in
`core/prompts/`.
"""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "local"
    DATABASE_URL: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    # Forced/structured output isn't uniform across providers (`tool_choice`
    # behaves differently on e.g. Ollama, §3.6). `agents/chat/nodes/classify.py`
    # reads this to pick the `with_structured_output(method=...)` strategy;
    # "json_mode"/"guided_json" are the documented fallbacks for providers
    # that don't support `"json_schema"`.
    STRUCTURED_OUTPUT_MODE: str = "json_schema"
    EMBEDDING_MODEL: str = "Qwen3-Embedding-0.6B"
    EMBEDDING_DIMENSION: int = 1024
    CONFIG_DIR: str = "config"
    USE_LOCAL_RETRIEVAL: bool = False
    RERANK_ENABLED: bool = True
    # Self-hosted `bge-reranker-v2-m3` (or `Qwen3-Reranker`) endpoint (§3.8).
    # Blank -- even with `RERANK_ENABLED=true` -- degrades `RerankedRetrieval`
    # to a warn-once no-op passthrough rather than failing retrieval outright
    # (design principle #4, offline-first): a client that hasn't stood up a
    # reranker yet still gets hybrid RRF results, just unreranked.
    RERANKER_BASE_URL: str = ""
    RERANKER_MODEL: str = "bge-reranker-v2-m3"
    REDIS_URL: str = ""
    STREAM_DURABLE: bool = False
    GUARDRAILS_ENABLED: bool = False
    RATE_LIMIT_PER_MIN: int = 0
    MAX_GRAPH_HOPS: int = 6
    TURN_BUDGET_SECONDS: float = 90.0
    AUTH_ENABLED: bool = True
    JWT_SECRET: str = "change-me"
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PROMPTS: bool = False
    SESSION_SWEEPER_ENABLED: bool = False
    # Not part of the §3.2 snippet's core list either, but needed as soon as
    # `LANGFUSE_PROMPTS=true` asks `core/prompts/engine.py` to actually reach
    # a self-hosted Langfuse instance (§3.5) -- already documented in
    # `.env.example`'s Observability section, just missing from `Settings`
    # until this step wired the client that reads them.
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3000"
    LANGFUSE_PROMPT_LABEL: str = "production"
    MCP_ENABLED: bool = False

    # Not part of the §3.2 snippet's core list, but needed immediately by
    # `main.py`'s CORS wiring (§3.9: "explicit `CORS_ALLOW_ORIGINS` list;
    # never `*` with credentials") — declared here rather than hard-coded so
    # it stays in the same `.env`-driven, per-client-configurable tier as
    # everything else.
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _fail_fast_on_placeholder_jwt_secret(self) -> Settings:
        """Refuse to boot with the placeholder JWT secret outside local dev.

        `JWT_SECRET=change-me` is a safe default for offline-first local dev
        (no external credential required to boot), but shipping it to
        staging/prod would mean every issued token is forgeable with a
        publicly known secret. Fail fast at process start, not at the first
        auth request.
        """
        if self.JWT_SECRET == "change-me" and self.ENVIRONMENT != "local":
            raise ValueError(
                "JWT_SECRET is still the placeholder 'change-me' with "
                f"ENVIRONMENT={self.ENVIRONMENT!r}. Set a real secret "
                "(e.g. `openssl rand -hex 32`) before starting outside local dev."
            )
        return self


settings = Settings()
