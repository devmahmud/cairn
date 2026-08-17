# Cairn — top-level dev workflow (BLUEPRINT.md §5).
#
# Targets below call into backend/ (uv) and frontend/ (pnpm) tooling that lands
# in later scaffold steps (BLUEPRINT.md §8) — `make help` always works; targets
# that shell out to not-yet-created project files will start working as those
# steps land.

.DEFAULT_GOAL := help

COMPOSE ?= docker compose

.PHONY: help setup run test up down migrate seed ingest contract contract-check up-langfuse up-litellm

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend (uv) + frontend (pnpm) dependencies
	cd backend && uv sync
	cd frontend && pnpm install

run: ## Run backend (fastapi dev) + frontend (vite dev) — needs `make up` for db/redis
	cd backend && uv run fastapi dev src/main.py &
	cd frontend && pnpm dev

test: ## Run backend (pytest) + frontend (vitest) test suites
	cd backend && uv run pytest
	cd frontend && pnpm test

up: ## Start the lean local stack (postgres+pgvector, redis, backend, frontend)
	$(COMPOSE) up -d

down: ## Stop the local stack
	$(COMPOSE) down

migrate: ## Apply backend Alembic migrations
	cd backend && uv run alembic upgrade head

seed: ## Seed the database with a sample user + conversation
	cd backend && PYTHONPATH=src uv run python -m scripts.seed

ingest: ## Ingest backend/data/sample_corpus into pgvector (chunks + embeddings)
	cd backend && PYTHONPATH=src uv run python -m modules.ingestion.cli

contract: ## Regenerate the frontend TS contract from the backend's OpenAPI schema
	cd frontend && pnpm run contract

contract-check: ## Fail if the committed TS contract has drifted from the backend's OpenAPI schema (CI)
	cd frontend && pnpm run contract:check

up-langfuse: ## Start the opt-in Langfuse observability stack (web+worker+clickhouse+redis+minio)
	$(COMPOSE) -f docker-compose.langfuse.yml up -d

up-litellm: ## Start the opt-in LiteLLM gateway proxy (budgets/rate-limit/fallback)
	$(COMPOSE) -f docker-compose.litellm.yml up -d
