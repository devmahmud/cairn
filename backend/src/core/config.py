"""Static, boot-time settings (tier 1 of 3); tier 2 is core/runtime_config.py, tier 3 is core/prompts/ hot reload."""

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
    # Not uniform across providers (e.g. Ollama's tool_choice); "json_mode"/"guided_json" are fallbacks for providers without "json_schema".
    STRUCTURED_OUTPUT_MODE: str = "json_schema"
    EMBEDDING_MODEL: str = "Qwen3-Embedding-0.6B"
    EMBEDDING_DIMENSION: int = 1024
    CONFIG_DIR: str = "config"
    USE_LOCAL_RETRIEVAL: bool = False
    RERANK_ENABLED: bool = True
    # Blank degrades RerankedRetrieval to a no-op passthrough rather than failing retrieval outright, even with RERANK_ENABLED=true.
    RERANKER_BASE_URL: str = ""
    RERANKER_MODEL: str = "bge-reranker-v2-m3"
    REDIS_URL: str = ""
    STREAM_DURABLE: bool = False
    GUARDRAILS_ENABLED: bool = False
    RATE_LIMIT_PER_MIN: int = 0
    MAX_GRAPH_HOPS: int = 6
    TURN_BUDGET_SECONDS: float = 90.0
    MAX_HISTORY_MESSAGES: int = 24
    AUTH_ENABLED: bool = True
    JWT_SECRET: str = "change-me"
    # Short-lived by design: access tokens verify statelessly (no DB round trip); the revocable refresh_tokens table bounds exposure instead.
    ACCESS_TOKEN_LIFETIME_SECONDS: int = 3600
    REFRESH_TOKEN_LIFETIME_SECONDS: int = 60 * 60 * 24 * 30
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PROMPTS: bool = False

    # --- Guardrails ------------------------------------------------------
    # Blank degrades to the deterministic denylist + PII layers only, even with GUARDRAILS_ENABLED=true.
    GUARDIAN_MODEL_BASE_URL: str = ""
    GUARDIAN_MODEL_NAME: str = "granite-guardian-3.3-8b"
    GUARDIAN_MODEL_RISK_NAME: str = "jailbreak"
    GUARDIAN_MODEL_TIMEOUT_SECONDS: float = 10.0
    # Opt-in only, independent of GUARDRAILS_ENABLED -- llama_guard.py's license isn't OSI-approved open source.
    GUARDRAILS_LLAMA_GUARD_OPT_IN: bool = False
    LLAMA_GUARD_MODEL_BASE_URL: str = ""
    LLAMA_GUARD_MODEL_NAME: str = "llama-guard-3-8b"

    # --- Limits ------------------------------------------------------------
    # Concurrency cap on in-flight generations, independent of RATE_LIMIT_PER_MIN (a request-rate limit, not a concurrency cap).
    MAX_CONCURRENT_GENERATIONS: int = 10
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3000"
    LANGFUSE_PROMPT_LABEL: str = "production"
    MCP_ENABLED: bool = False

    # Explicit origin list; never "*" with credentials enabled.
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _fail_fast_on_placeholder_jwt_secret(self) -> Settings:
        """Refuse to boot with the placeholder JWT secret outside local dev -- it's a publicly known value."""
        if self.JWT_SECRET == "change-me" and self.ENVIRONMENT != "local":
            raise ValueError(
                "JWT_SECRET is still the placeholder 'change-me' with "
                f"ENVIRONMENT={self.ENVIRONMENT!r}. Set a real secret "
                "(e.g. `openssl rand -hex 32`) before starting outside local dev."
            )
        return self


settings = Settings()
