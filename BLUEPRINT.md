# Cairn — Architecture Blueprint (v3)

*A durable, checkpointed foundation for building agent chat apps — the marker that always knows the way back.*

A reusable, **open-source, self-hostable** template for building streaming LLM/agent chat
applications, designed with no Azure-specific or remote-config dependency from the outset — hardened
against a 6-lens adversarial review (orchestration, RAG/data, backend, streaming/FE, prod/security/cost,
reference-architecture), and a v3 staleness/licensing/multi-client refresh (9-agent research audit,
Aug 2026).

> **Status:** Blueprint, v3 (validated). The runnable scaffold is generated from this document.
> This file is the durable reference you copy into future projects.

## Changelog — what v3 fixed (Aug 2026 refresh)

v2 was correct when written (2026-06-17); nothing in it was architecturally wrong. Two months in a
fast-moving stack still produced real drift: one factual reversal, one API deprecation-claim that was
backwards, two open-source **license traps** that would have quietly leaked non-permissive terms into
every client fork, an OWASP list renumbering, and a genuine gap on the thing this refresh was triggered
by — "we'll reuse this for different clients, not just the pet one." Also folds in an explicit
durability contract per the pet-project's own hard lesson: an agent loop must checkpoint every step,
not just resume at the conversation level.

- **SSE library → drop `sse-starlette`.** FastAPI shipped **native** `fastapi.sse.EventSourceResponse`
  (v0.135, ~March 2026) solving the exact problems `sse-starlette` was chosen for: heartbeat pings,
  correct disconnect handling, and **built-in `Last-Event-ID` resume** — one fewer third-party dependency
  for a capability the template needed anyway (§3.7, §1).
- **Guardrail model → drop Llama Guard as the default.** Its license (Llama Community License) is
  **not OSI-approved open source**: a 700M-MAU commercial cap, a binding Acceptable Use Policy, and
  mandatory attribution/naming — all of which would transitively bind every client this template is
  forked into. Default swapped to **IBM Granite Guardian** (Apache-2.0, current prompt-injection
  leaderboard leader); Llama Guard demoted to an opt-in with an explicit license callout (§3.12).
  NeMo Guardrails itself (Apache-2.0, orchestration only) is unaffected and stays.
- **LiteLLM → document the open-core boundary + pin for supply-chain safety.** Core proxy is MIT, but
  RBAC/audit-log/SSO-beyond-5-users/secret-manager-integrations live behind a paid `enterprise/` tier —
  now documented explicitly so a client engagement doesn't discover it mid-project. Separately: pin
  **≥1.83.10** — v1.82.7/1.82.8 were a confirmed PyPI supply-chain compromise (Mar 2026), and several
  CVEs (incl. a pre-auth SQLi and a KEV-listed command injection) are fixed only at ≥1.83.x (§3.13).
- **OWASP LLM Top 10 → re-numbered to the 2026 edition.** Excessive Agency jumped LLM06→**LLM03**
  (biggest riser — real agentic/tool-use incidents); Unbounded Consumption LLM10→**LLM06**; Improper
  Output Handling fell LLM05→**LLM10**. Two new categories added: **LLM04 Supply Chain** and **LLM05
  Data/Model Poisoning**, both directly relevant to this template's pinned models and RAG ingestion
  (§3.12).
- **Multi-client story → made explicit instead of assumed.** "Neutral core, domain in `examples/`"
  was already the right instinct but under-specified: added decision criteria for copy-per-client vs.
  shared multi-tenancy, **Copier** (not a one-shot copy) as the scaffolding tool so client forks can
  pull upstream fixes via 3-way merge, a **client config manifest** so per-client divergence stays in
  one low-conflict place, and a documented **shared-multi-tenant mode** (tenant_id + Postgres RLS) as
  the alternative once client count outgrows copy-per-client (§3.14 — new).
- **Agent-loop durability → made explicit, not just implied by "we use a checkpointer."** LangGraph
  checkpoints after every superstep (node), so a process crash mid-graph resumes from the last
  completed **node**, not from turn zero — this was true in v2 but underspecified. Added the new
  (LangGraph 1.2) `durability` mode, a `thread_id` format constraint, and an explicit idempotency rule
  for node-level retries so re-executed nodes with side effects (tool calls) can't double-fire (§3.6).
- **Embeddings default → self-hosted, matching the template's own "not tied to one vendor" principle.**
  Default swapped from OpenAI `text-embedding-3-small` to **Qwen3-Embedding-0.6B** (Apache-2.0,
  self-hosted via the same `OPENAI_BASE_URL` override already used for the LLM); hosted API kept as an
  opt-in (§3.8).
- **Smaller fixes** — pgvector version floor `>=0.8` → `>=0.8.2` (parallel-HNSW-build CVE fixed there);
  caveat that Postgres `tsvector` is a BM25 *approximation*, not real BM25 (name `pg_search`/
  `pg_textsearch` as the real-BM25 option); Vite 7→8 (Rolldown default, built-in tsconfig-paths); shadcn
  `@base-ui/react` corrected from "non-default substrate" to shadcn's default-since-July-2026 primitive;
  `astream_events(v2)` corrected — it is **not** deprecated (only the older v1 event format is); Presidio
  noted as now independently governed (no longer Microsoft-owned) — a point in its favor, not a concern.

## Changelog — what v2 fixed (from the validation pass)

The bones of v1 were sound, but the review found 3 correctness bugs, several production gaps, and 2
mis-architected layers. v2 changes:

- **Persistence/resume/HITL** → adopt LangGraph's **`AsyncPostgresSaver` checkpointer** as the
  execution-state + resume + human-in-the-loop backbone; the event log is demoted to an optional
  **audit/analytics projection** (§3.3, §3.6).
- **Transactions** → explicit boundaries: commit-per-request for REST; **session-per-turn
  unit-of-work** in the streamer, never spanning the LLM call; idempotency key on `/chat` (§3.3, §3.7).
- **RAG** → from naive cosine to production: **HNSW index** (v1 was a seq scan), **hybrid BM25+vector
  with RRF**, a **reranker** stage, a **chunking/ingestion pipeline**, calibrated abstention, and
  pgvector ≥0.8 iterative scans for filtered search (§3.3, §3.8).
- **Resumable streaming** → generation decoupled onto a **Redis stream**, `id:`-stamped events, a
  resume endpoint, and a stop endpoint; client reconnect with `Last-Event-ID` (§3.7, §4.2).
- **LLM security** → a `guardrails` layer (input rail, output rail, PII redaction) mapped to the
  **OWASP LLM Top 10**, no-op by default (§3.9, §3.12).
- **Cost/abuse** → **LiteLLM proxy** + per-`/chat` rate limit + concurrency cap + per-turn wall-clock
  budget + graph-hop cap (§3.13).
- **Middleware** → **drop the global response envelope**; errors via exception handlers; request-id as
  pure-ASGI; SSE via **`sse-starlette`** (no `BaseHTTPMiddleware` around the stream). This also makes
  OpenAPI truthful, enabling full typed-client codegen (§3.9, §4.3).
- **Runtime control without remote config** → your **no-cloud-config** rule is kept, but a *local*
  control plane is added: **Langfuse prompt management** (already in stack) + a **DB config-override
  table** + **`watchfiles` hot reload** (§3.2, §3.5).
- **Generic core.** The core schema is domain-neutral (`users/conversations/messages/documents`); the
  shipped example is a neutral **docs-assistant**; any domain-specific logic (slots, entities, routing
  tables) lives under `examples/` as a strippable pack (§2, §3.3).
- **Streaming technique corrected** → structured/forced-tool nodes stream via a **custom writer**, not
  `on_chat_model_stream` (which carries only tool-call chunks) (§3.6, §3.7).
- **Smaller fixes** → drop the generic filter DSL for explicit `select()`; `visibilitychange` fix for
  the typewriter; `openapi-typescript` codegen; `/health/live` + `/health/ready`; Prometheus `/metrics`;
  sweeper leader-election; `JWT_SECRET` fail-fast; CORS hardening; MCP demoted to an appendix.

---

## 0. TL;DR — what you get

- **Backend:** FastAPI + LangGraph (Python 3.13, `uv`). Layered `core / modules / agents`. Provider-
  agnostic LLM, RAG over **pgvector (hybrid + rerank)**, prompts-as-files + a local runtime-control
  plane, contract-first SSE, **durable graph state via a Postgres checkpointer**.
- **Frontend:** Vite + React 19 + TS SPA. Feature-Sliced. **Resumable** SSE pipeline (reconnect mid-
  stream) with a visibility-aware typewriter.
- **Data:** PostgreSQL 16 + **pgvector** (rows + embeddings + FTS in one store). SQLAlchemy 2 async +
  Alembic. **Explicit transaction boundaries.**
- **Config:** `pydantic-settings` from `.env`; **no cloud config provider**. Runtime control via a DB
  override table + `watchfiles` + Langfuse prompts (all local/self-hosted).
- **Safety & cost:** OWASP-mapped **guardrail rails** (off by default) + **LiteLLM**-fronted budgets,
  rate limits, concurrency caps.
- **Observability:** self-hosted **Langfuse** + **structlog** + **Prometheus** `/metrics`. Liveness +
  readiness probes.
- **Local dev:** one `docker-compose.yml` (Postgres+pgvector, Redis, backend, frontend); split-out
  Langfuse + optional LiteLLM.
- **CI/CD:** GitHub Actions → lint/type/test + a **prompt/guardrail regression gate** → images to ghcr.io.

### Design principles

1. **Layered, one composition root.** Business logic in vertical `modules/`; infra in `core/`. Deps
   flow one way: `agents/modules → core`.
2. **Contract-first streaming.** SSE shapes defined once (Pydantic), surfaced in OpenAPI, generated to
   TS. The graph emits no SSE; one streamer translates graph events to the wire.
3. **Provider-agnostic agents.** One `get_llm()` swap-point → OpenAI / Ollama / vLLM / **LiteLLM**.
4. **Offline-first.** Every external dependency degrades to a local/no-op default, so the app boots and
   tests run with zero credentials (`USE_LOCAL_RETRIEVAL=true`, guardrails no-op, in-request streaming).
5. **Config is local, but still controllable at runtime.** No cloud provider; kill switches, hot prompts,
   and flags come from your own Postgres + Langfuse + file-watch.
6. **Durable by default, at the step level.** The checkpointer persists state after **every node**
   (LangGraph "superstep"), not just at turn boundaries — a crash mid-graph resumes from the last
   completed node, not from turn zero. Turns are transactional; streams are resumable. A "proper" agent
   survives a dropped connection, a killed pod, or a mid-node crash (§3.6).
7. **Neutral core, domain in `examples/`.** The core knows `users / conversations / messages /
   documents`. Anything domain-shaped (slots, entities, routing tables) ships as a strippable pack.
   This is also the mechanism the multi-client reuse model is built on (§3.14).

---

## 1. Stack

| Concern | Choice | Notes |
|---|---|---|
| Web framework | **FastAPI** (`fastapi[standard]`) | ASGI, streaming, OpenAPI |
| SSE | **FastAPI native `fastapi.sse.EventSourceResponse`** | built into FastAPI ≥0.135 (Mar 2026): heartbeat pings, correct disconnect handling, **built-in `Last-Event-ID` resume**. `sse-starlette` dropped — this made it redundant. Fallback only if pinned <0.135. |
| Agent runtime | **LangGraph + LangChain** (MIT core packages only) | graph orchestration + **`AsyncPostgresSaver` checkpointer**; never depend on `langgraph-api`/`langgraph-cli`/Platform (Elastic License 2.0, commercial) |
| LLM client | **`langchain-openai` `ChatOpenAI`** | OpenAI-compatible; `OPENAI_BASE_URL` → Ollama/vLLM/LiteLLM |
| **LLM gateway** | **LiteLLM (self-hosted proxy)**, pinned **≥1.83.10** | per-user budgets, RPM/TPM, fallback, retries — config-file driven; open-core (RBAC/audit-log/SSO>5/secret-mgr integrations are paid `enterprise/`); pin for supply-chain (§3.13) |
| DI | **`dependency-injector`** | singleton graph only; justified by CLI/eval reuse (native `Depends` is a fine simpler alternative; `Dishka` is a newer async-scoped option if reconsidering) |
| Config | **`pydantic-settings`** + DB override table + **`watchfiles`** | no cloud provider |
| Database | **PostgreSQL 16** | rows + vectors + FTS |
| ORM | **SQLAlchemy 2 (async, `asyncpg`)** | explicit transactions |
| Migrations | **Alembic** (+ `checkpointer.setup()` for LangGraph tables) | |
| Vector / RAG | **pgvector ≥0.8.2** (HNSW) + **tsvector** FTS approximation + **RRF** | hybrid; iterative scans for filtered search; `≥0.8.2` fixes a parallel-HNSW-build CVE; swap FTS for `pg_search`/`pg_textsearch` when real BM25 (not just tsvector's approximation) matters |
| Reranker | **`bge-reranker-v2-m3`** (self-hosted, Apache-2.0) | behind the retrieval Protocol; `Qwen3-Reranker` (Apache-2.0) is the current higher-accuracy alternative |
| Embeddings | **Self-hosted `Qwen3-Embedding-0.6B`** (Apache-2.0), same `OPENAI_BASE_URL` pattern | OpenAI `text-embedding-3-small` kept as an opt-in hosted alternative; `BGE-M3` (MIT) if multilingual/hybrid dense+sparse is needed |
| Guardrails | **Presidio** (PII, MIT, independently-governed) + **Granite Guardian** (Apache-2.0, guard model, called directly) | off by default, no-op; NeMo Guardrails (Apache-2.0) is a registerable optional orchestration layer on top, not shipped as pre-authored Colang (§3.12); Llama Guard is opt-in only — its license is not OSI-approved |
| Cache / resume / rate-limit | **Redis 7** | resumable streams, `slowapi`, cache |
| Observability | **Langfuse** + **structlog** + **`prometheus-fastapi-instrumentator`** | traces + logs + metrics; Langfuse core is MIT self-hosted, EE tier (SCIM/audit-log) is paid |
| Auth | **`fastapi-users`** (MIT, feature-frozen since v15.0.1 — stable, security-patched) | on by default; conversations are owned per-user, not optional (§3.9) |
| Tooling (BE) | **uv · ruff · mypy · pytest · pre-commit · mise** | |
| Frontend | **Vite 8 + React 19 + TS** SPA · Zustand · Tailwind v4 + shadcn(`@base-ui/react`, now shadcn's default substrate) | |
| Contract sync | **`openapi-typescript`** off FastAPI's OpenAPI | full REST client + SSE types; `@hey-api/openapi-ts` if generated SDK methods/hooks (not just types) are wanted |
| FE test | **Vitest + Testing Library + Playwright** | |
| Containers / registry / CI | Docker + compose · **ghcr.io** · GitHub Actions | |
| Client scaffolding | **Copier** (MIT) | generates each client fork; `copier update` 3-way-merges upstream template fixes into an already-customized fork (§3.14) |

### No managed-cloud dependency, by design

Every stateful concern is self-hosted and OSS: **Postgres/SQLAlchemy** for rows (no managed
document/NoSQL service); **pgvector hybrid+rerank** for search (no managed search service); **local
files** for blobs; a **local control plane** — `.env` + a DB override table + `watchfiles` — instead of a
cloud config service; **`.env` + optional SOPS+age** for secrets (no cloud key-vault dependency);
**compose/ghcr.io** for build+deploy (no proprietary container platform); `get_llm()` is
OpenAI-API-compatible so any provider — hosted or self-hosted — is a `OPENAI_BASE_URL` swap, never a
hard dependency on one vendor's model API.

---

## 2. Repository layout (monorepo)

```
cairn/
├── README.md  BLUEPRINT.md  NEW_CLIENT_CHECKLIST.md  LICENSE
├── copier.yml                     # Copier template config (questions/variables) — each client fork
│                                  #   gets a `.copier-answers.yml` auto-written by `copier copy`, enabling
│                                  #   `copier update` to 3-way-merge upstream fixes later (§3.14)
├── client.config.yaml             # the ONE file (+ examples/<domain>/) a client fork should ever diverge on (§3.14)
├── docker-compose.yml            # postgres+pgvector, redis, backend, frontend
├── docker-compose.langfuse.yml   # heavy observability stack (opt-in)
├── docker-compose.litellm.yml    # optional LLM gateway (budgets/rate-limit/fallback)
├── Makefile  mise.toml  .env.example
├── .github/workflows/            # ci.yml, eval-gate.yml, docker.yml
│
├── backend/
│   ├── pyproject.toml  ruff.toml  mypy.ini  alembic.ini  litellm.config.yaml
│   ├── Dockerfile
│   ├── config/                   # versioned, local
│   │   ├── prompts/*.j2          #   Jinja prompt templates (Langfuse-overridable)
│   │   └── behavior/*.yaml       #   rules, guardrail patterns, routing
│   ├── alembic/                  # migrations (incl. pgvector + FTS index)
│   ├── data/sample_corpus/       # tiny docs to ingest for the example assistant
│   ├── src/
│   │   ├── main.py  routers.py
│   │   ├── core/                 # infra, no business logic
│   │   │   ├── config.py  runtime_config.py     # settings + DB override + watchfiles
│   │   │   ├── di/container.py
│   │   │   ├── db/{engine,base}.py  repository/base.py
│   │   │   ├── prompts/          # PromptEngine (file + Langfuse + hot reload)
│   │   │   ├── sse/framing.py    # format_event (+ id:), heartbeat
│   │   │   ├── stream/resume.py  # Redis-backed durable stream bus
│   │   │   ├── guardrails/       # input rail · output rail · PII (no-op default)
│   │   │   ├── limits/           # rate limit · concurrency · per-turn budget
│   │   │   ├── middleware/  errors/  security/  observability/  cache/
│   │   ├── modules/              # vertical slices
│   │   │   ├── chat/             # streaming endpoint + SSE contract + streamer
│   │   │   ├── conversations/    # conversation/message lifecycle REST + sweeper
│   │   │   ├── retrieval/        # hybrid RAG over pgvector (Protocol+factory+fixture)
│   │   │   ├── embedding/  ingestion/  auth/  health/
│   │   ├── agents/               # LangGraph; emits NO SSE; checkpointed
│   │   │   ├── llm.py  config.py  base.py  registry.py
│   │   │   └── chat/{agent,graph,state,schemas}.py  nodes/
│   │   └── examples/             # ← strippable domain packs; ships one neutral worked example (docs-assistant/)
│   └── tests/                    # unit / integration / eval (+ retrieval & injection evals)
│
└── frontend/
    ├── package.json  vite.config.ts  Dockerfile  nginx.conf
    └── src/{app, features/{chat,...}, shared/{api,types,components,lib}}
```

---

## 3. Backend architecture

### 3.1 Layers

`core/` (infra) ← `modules/` (vertical slices: router→controller→service→repository/schemas) and
`agents/` (LangGraph, transport-agnostic). `examples/` holds domain packs that depend on core but are
deletable. Deps flow one way.

### 3.2 Config — local, but runtime-controllable

Three tiers, **all self-hosted / in-repo / in-your-DB** (no cloud provider):

1. **Static (`core/config.py`)** — `pydantic-settings` from `.env`. Boot-time, immutable. (Same as v1.)
   Add a fail-fast: refuse to start if `JWT_SECRET == "change-me"` and `ENVIRONMENT != local`.
2. **Runtime overrides (`core/runtime_config.py`)** — a `config_overrides` Postgres table
   (`key, value, updated_at`) read through a small cached accessor with Postgres `LISTEN/NOTIFY` (or a
   short TTL) so an `UPDATE` flips behavior **cluster-wide without redeploy**. This is the **kill-switch
   / feature-toggle** plane (e.g. `tool.web_search.enabled=false`, `guardrails.strict=true`).
3. **Prompts/behavior files + hot reload** — `config/prompts/*.j2` and `config/behavior/*.yaml` watched
   by **`watchfiles`** in every environment; edit a guardrail/prompt file → reload, no rebuild.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ENVIRONMENT: str = "local"
    DATABASE_URL: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""            # → LiteLLM/Ollama/vLLM; also fronts self-hosted embeddings (§3.8)
    OPENAI_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "Qwen3-Embedding-0.6B"   # self-hosted (Apache-2.0) via vLLM/TEI/Ollama; "text-embedding-3-small" is the opt-in hosted alternative
    EMBEDDING_DIMENSION: int = 1024
    CONFIG_DIR: str = "config"
    USE_LOCAL_RETRIEVAL: bool = False
    RERANK_ENABLED: bool = True
    REDIS_URL: str = ""                  # empty → simple (non-resumable) streaming + no cache
    STREAM_DURABLE: bool = False         # true → Redis-backed resumable streams (needs REDIS_URL)
    GUARDRAILS_ENABLED: bool = False     # true → input/output rails + PII
    RATE_LIMIT_PER_MIN: int = 0          # 0 → off
    MAX_GRAPH_HOPS: int = 6
    TURN_BUDGET_SECONDS: float = 90.0
    AUTH_ENABLED: bool = True    # conversations are per-user by default; set False only for eval/CI runs that don't need identity
    JWT_SECRET: str = "change-me"
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PROMPTS: bool = False       # true → fetch prompts by label, fallback to bundled files
    SESSION_SWEEPER_ENABLED: bool = False
    MCP_ENABLED: bool = False
```

> **Why this satisfies "no remote config":** there is no external config *service* and no cloud
> credential. Runtime control lives entirely in **your** Postgres, **your** file tree, and **your**
> self-hosted Langfuse — all of which you already run. You keep kill switches and hot prompt iteration
> (table stakes for an agent) without a cloud dependency.

### 3.3 Persistence — PostgreSQL + pgvector, with real transactions

**Neutral core schema** (any domain-specific tables live under `examples/`, not here):

| Table | Holds |
|---|---|
| `users` | auth identity + profile JSONB |
| `conversations` | id, user_id, title, status, `summary`, `summary_embedding vector`, timestamps |
| `messages` | id, conversation_id, role, content, `artifacts jsonb`, `citations jsonb`, created_at — **the queryable history of record** |
| `documents` / `chunks` | RAG corpus; `chunks` has `embedding vector(1024)` (matches `EMBEDDING_DIMENSION`) + `content_tsv tsvector` (hybrid) |
| `config_overrides` | runtime control plane (§3.2) |
| `events` *(optional)* | append-only **audit/analytics projection** (tool calls, state transitions) — *not* the memory backbone |
| LangGraph checkpoint tables | created by `AsyncPostgresSaver.setup()` — execution state per `thread_id = conversation_id` |

**Execution state lives in the checkpointer, not a hand-rolled log.** LangGraph's `AsyncPostgresSaver`
persists graph state per thread, giving **durable resume, `interrupt()` HITL, and time-travel** for free
(you already run Postgres). Your `conversations`/`messages` tables remain the clean, queryable
system-of-record for the UI/REST and analytics. (v1 used a custom event log *as* the backbone; the
review flagged this as reimplementing — and under-delivering — what the checkpointer provides.)

**Engine + session (`core/db/engine.py`):**

```python
engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True,
                             pool_size=20, max_overflow=10, pool_recycle=1800)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession]:
    async with SessionLocal() as s:
        try:
            yield s
            await s.commit()          # commit-per-request for REST
        except Exception:
            await s.rollback()
            raise
```

**Transaction rules (the v1 gap):**
- **REST endpoints** → `get_session` commits per request (above).
- **The chat turn does NOT use a request-scoped session.** It would pin a pool connection for the whole
  stream. Instead, inject the **`async_sessionmaker`** into the streamer and open **two short
  transactions** — one to read turn state at the start, one to persist results at the end — **never held
  across `astream`/the LLM call**. The checkpointer manages its own connection for graph-state writes.
- **Idempotency** → `/chat` accepts a client `idempotency_key`; the user message insert is
  `INSERT ... ON CONFLICT DO NOTHING` so a retry/reconnect can't double-write or double-run.

**pgvector — hybrid, indexed, filter-safe (the v1 RAG gap):**

```sql
-- migration
CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector >= 0.8.2 (0.8.0/0.8.1 have a parallel-HNSW-build CVE; pin 0.8.6+)
ALTER TABLE chunks ADD COLUMN content_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
CREATE INDEX ON chunks USING gin (content_tsv);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
-- per session: SET hnsw.ef_search = 40;  SET hnsw.iterative_scan = 'relaxed_order';  (filtered search)
-- builds: raise maintenance_work_mem (4–16GB) or HNSW falls to a 10–50x slower disk path
```

Retrieval = **lexical (Postgres FTS) ⊕ vector, fused with Reciprocal Rank Fusion**, then a
**cross-encoder reranker** — all behind one Protocol (§3.8). Vector-only cosine (v1) smears
identifiers/SKUs/exact terms; hybrid+rerank is the 2026 production default. **Caveat:** Postgres
`tsvector`/`ts_rank` is a BM25 *approximation* — no IDF weighting, no document-length normalization —
not real BM25. That's fine as the zero-extra-dependency default; if lexical ranking quality matters
(exact-term-heavy corpora), swap in **`pg_search`** (ParadeDB, Tantivy-backed) or **`pg_textsearch`**
for true BM25 in-Postgres, same Protocol.

**Repository (`core/repository/base.py`):** thin generic CRUD only (`get/add/delete`). **No magic
`field__op` filter DSL** — write explicit, typed `select()` query methods per repository (clearer,
`mypy`-friendly, supports joins/projections). Add keyset pagination + a default `LIMIT` on list reads.

### 3.4 DI composition root (`core/di/container.py`)

`dependency-injector` for the **singleton graph only** — justified because the same graph + services run
**outside FastAPI** (the CLI eval harness). Native FastAPI `Depends` is a perfectly good simpler
alternative if you don't need that reuse; pick one wiring model per concern and don't mix `Provide` and
`Depends` for the same kind of dependency.

```python
class Container(containers.DeclarativeContainer):
    config = providers.Object(settings)                      # seeded once; no from_dict refresh
    sessionmaker = providers.Object(SessionLocal)            # injected into the streamer (§3.3)
    loader = providers.Singleton(FileSystemJ2Loader, base_path=settings.CONFIG_DIR + "/prompts")
    prompt_engine = providers.Singleton(PromptEngine, loader=loader)         # + Langfuse overlay (§3.5)
    embedding_service = providers.Singleton(OpenAIEmbeddingService, ...)
    retrieval_service = providers.Singleton(build_retrieval_service,
                                            use_local=settings.USE_LOCAL_RETRIEVAL, ...)
    checkpointer = providers.Singleton("langgraph.checkpoint.postgres.aio.AsyncPostgresSaver", ...)
    chat_agent = providers.Singleton(ChatAgent, prompt_engine=prompt_engine,
                                     retrieval_service=retrieval_service, checkpointer=checkpointer)
    chat_streamer = providers.Factory(ChatStreamer, chat_agent=chat_agent, sessionmaker=sessionmaker)
```

### 3.5 Prompts & behavior — files + Langfuse + hot reload

`PromptEngine` resolves a prompt in this order, **degrading gracefully**:
1. If `LANGFUSE_PROMPTS=true`: fetch by label (`production` / `prod-a` / `prod-b`) → enables **hot prompt
   updates, versioning, rollback, A/B** with no redeploy, using the Langfuse you already self-host.
2. **Fallback** to the bundled `config/prompts/*.j2` (cached, watched by `watchfiles`) — so a Langfuse
   outage degrades to last-known-good local prompts, preserving offline-first.

Behavioral YAML (`config/behavior/*.yaml`: routing, guardrail patterns, rules) is filesystem + hot
reload + overridable via the `config_overrides` table.

### 3.6 Agents (`agents/`) — provider-agnostic, checkpointed, resilient

**LLM factory** — the swap-point. Point `OPENAI_BASE_URL` at **LiteLLM** (recommended) to get budgets/
fallback/rate-limit for free, or at Ollama/vLLM for fully local.

```python
def get_llm(role: str = "answer") -> ChatOpenAI:
    cfg = role_config(role)
    return ChatOpenAI(model=cfg.model, temperature=cfg.temperature,
                      api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL or None,
                      max_retries=3, timeout=cfg.timeout,
                      callbacks=[langfuse_handler()] if settings.LANGFUSE_ENABLED else [])
```

**The graph** demonstrates each node type; compiled **with the checkpointer**:

```
START → input_rail → classify → route ─┬→ answer
                                       ├→ rag        (hybrid retrieve → abstain-or-ground → cite)
                                       ├→ tool        (external API / MCP; ToolNode loop, hop-capped)
                                       └→ guardrail   (refuse / interrupt() → human) → output_rail → END
graph.compile(checkpointer=checkpointer)            # thread_id = str(conversation_id) — a UUID; Postgres'
                                                     # checkpoint thread_id column is bounded, don't use free text
```

**Step-level durability — the actual contract, spelled out:** the checkpointer writes state after
**every superstep** (each node's execution), not just at turn start/end. A process crash, killed pod, or
dropped connection mid-graph resumes the graph from the **last completed node** on the next call with
the same `thread_id` — not from the beginning of the turn. Three things make this a real guarantee
rather than an assumption:
- **`durability` mode (LangGraph ≥1.2):** `graph.astream(..., durability="sync")` writes the checkpoint
  *before* the next step runs (strongest guarantee, slightly higher latency); `"async"` writes
  concurrently with the next step (lower latency, a narrow crash window where the last step's result
  could be lost); `"exit"` only checkpoints at graph exit (weakest — don't use it here). **Default to
  `"sync"`** for this template — a chat turn is not high-enough-throughput for the latency difference to
  matter, and losing a step silently is worse than the extra round-trip.
- **Node-level retry (`RetryPolicy`) is a different guarantee than checkpoint/resume** — retry handles
  "this node's call failed, try again within the same run"; the checkpointer handles "the process died,
  pick up on the next request." Both are needed; neither substitutes for the other.
- **Idempotency on node re-execution.** If a node has already-fired side effects (a tool call, an
  external API write) and the process crashes *after* the effect but *before* the checkpoint write lands,
  a resume will re-run that node. Nodes with non-idempotent side effects (`tool`, primarily) must either
  be naturally idempotent (safe to call twice) or carry their own idempotency key so a replayed call is a
  no-op on the second attempt — don't rely on "the checkpointer already ran this" as a dedup mechanism,
  because the crash window above is exactly the case where it hasn't.

- **classify** — one forced-tool call → `{intent, confidence}`; low confidence → `unclear`.
- **route** — deterministic Python over `routing.yaml` (validated as best-practice, not legacy).
- **answer / rag / tool / guardrail** — workers. RAG abstains on low *reranker* score (calibrated, not
  `0.0`). `tool` is hop-capped (`MAX_GRAPH_HOPS`). `guardrail` can `interrupt()` for true HITL (resumable
  via the checkpointer), not just terminate.
- **input_rail / output_rail** — guardrail hooks (§3.12), no-op unless `GUARDRAILS_ENABLED`.

**Resilience:** per-node timeouts, a fallback ladder (classify
timeout→`unclear`, RAG-empty→defer, tool-error→graceful message), LangGraph `RetryPolicy` on LLM/tool
nodes, `max_retries` on the client, and a **per-turn wall-clock budget** wrapping the whole graph.

**Streaming technique (the v1 doc bug):** you **cannot** token-stream a structured/forced-tool node via
`on_chat_model_stream` (those events carry tool-call chunks, not content). So:
- **Plain-text nodes** → translated from the model stream.
- **Structured nodes** (RAG answer, etc.) → stream incremental text via a **custom writer**
  (`stream_mode="custom"` / `get_stream_writer()`); the streamer suppresses their raw model events.
Use `graph.astream(stream_mode=["updates","messages","custom"])` as the streaming API (stable,
multiplexed). Two corrections since v2: **`astream_events(version="v2")` is not on a deprecation path**
— only the older v1 event format is being deprecated, v2 remains current; its subgraph pitfall is real
though — subgraph events don't propagate to the parent stream unless you pass `subgraphs=True` (relevant
to MCP nesting, Appendix A). Separately, **LangGraph 1.2 (May 2026) introduced a typed-projection
event-streaming API** (`stream.messages`, `stream.values`, `stream.subgraphs`, `stream.output` —
independent, non-consuming iterators) that LangChain's docs now recommend for new applications, with
`stream_mode`-based `astream` repositioned as the lower-level option. It's ~3 months old as of this
writing — this template stays on `stream_mode=[...]` deliberately (more battle-tested, avoids re-learning
a brand-new surface mid-build) but the typed-projection API is worth adopting once it has more mileage;
don't read the choice as an oversight.

**Structured output across providers:** forced `tool_choice` isn't uniform (e.g. Ollama). Prefer
`with_structured_output(method="json_schema")` where supported; fall back to JSON-mode (Ollama
`format=`) or grammar-constrained decoding (vLLM `guided_json`). Expose `STRUCTURED_OUTPUT_MODE`.

### 3.7 SSE — contract, streamer, and **resumability**

**Wire contract (`modules/chat/sse.py`)** — Pydantic `_WireModel`s, snake→camel aliases, `format_event`
**now stamping a monotonic `id:`** per event (enables `Last-Event-ID` resume). Core event set:
`message_start · message_delta · message_end (+citations) · agent_switch · tool_result · decision ·
guardrail · error`. (Domain events like `slot_fill` belong to example packs, not the core.) **Register
these models in the OpenAPI schema** so the TS contract can be generated (§4.3).

**Two streaming modes:**
- **Simple (default, zero-dep):** FastAPI's native `EventSourceResponse` runs the producer in-request —
  no `sse-starlette` needed, and it already gives `Last-Event-ID`-based reconnect handling out of the
  box. Works offline. Good for first-run and local dev; graduate to durable mode below for true
  disconnect-then-resume-mid-turn (the in-request producer still dies with the request).
- **Durable (`STREAM_DURABLE=true`, needs Redis):** the producer is **decoupled from the request** — it
  writes `id:`-stamped frames to a **Redis stream** keyed by a server-generated `stream_id`; the HTTP
  handler tails Redis → client. Survives disconnects and server restarts; doesn't waste tokens on a
  dropped socket.

```python
# POST /chat            → starts a turn, returns/streams via EventSourceResponse (and a stream_id)
# GET  /chat/stream/{stream_id}?last_event_id=...   → replay-from-id then tail (reconnect)
# POST /chat/stream/{stream_id}/stop                → cancel the producer (true terminate vs disconnect)
```

The streamer uses FastAPI's native `EventSourceResponse` (correct disconnect + heartbeat handling built
in since FastAPI ≥0.135), emits `:ping` heartbeats, and is **not** wrapped by the
response-envelope/`BaseHTTPMiddleware` stack (§3.9). Errors mid-turn are
surfaced as an `error` **event** (the HTTP error path is gone once bytes flow). The post-stream
persistence block runs in its own short transaction (§3.3).

### 3.8 Retrieval — hybrid + rerank behind one Protocol

```python
class RetrievalService(Protocol):
    async def query(self, text: str, top_k: int, filters: dict | None = None) -> list[RetrievalDoc]: ...

def build_retrieval_service(*, use_local: bool, rerank: bool, **kw) -> RetrievalService:
    if use_local:
        return LocalFixtureRetrievalService()            # boots with zero deps
    svc = PgVectorHybridRetrievalService(**kw)           # BM25 ⊕ vector → RRF
    return RerankedRetrieval(svc, RERANKER) if rerank else svc
```

Pipeline: FTS + vector (overfetch ~3–5×) → **RRF fuse** → **`bge-reranker-v2-m3`** top-k → dedupe by
`parent_id`. (`Qwen3-Reranker`, also Apache-2.0, is the current higher-accuracy alternative if the
larger model footprint is acceptable.) Filtered queries set `hnsw.iterative_scan` to avoid post-filter
recall collapse. **Embeddings** are self-hosted by default — **`Qwen3-Embedding-0.6B`** (Apache-2.0,
Ollama-native, 1024-dim) behind the same `OPENAI_BASE_URL`-pointed OpenAI-compatible endpoint pattern
used for the LLM (via vLLM or Text-Embeddings-Inference); `BGE-M3` (MIT) is the alternative when
multilingual + hybrid dense/sparse retrieval is needed; a hosted API (`text-embedding-3-small`) remains
a documented opt-in for teams that don't want to self-host the embedding model. **Ingestion
(`modules/ingestion` + `make ingest`):** `RecursiveCharacterTextSplitter` (~512 tokens, ~15% overlap) →
batched embeddings → upsert with `parent_id` + embedding-version. **When to leave pgvector:** sound to
~1–5M vectors (some 2026 benchmarks push this to ~5–10M); beyond that, swap the index to
**pgvectorscale StreamingDiskANN** (stay in Postgres, actively maintained by Tiger Data, handles 50M+
vectors) or graduate to **Qdrant** — both behind the unchanged Protocol.

### 3.9 Cross-cutting (`core/`)

- **No global response envelope.** Endpoints return plain `response_model`s → OpenAPI is truthful →
  full typed client codegen works. (v1's `{success,data,message}` middleware broke this and buffered
  streams.)
- **Errors** → FastAPI **exception handlers** (typed exceptions → consistent JSON), not
  `BaseHTTPMiddleware`.
- **Request-id** → a tiny **pure-ASGI** middleware (`x-request-id`); access logging via structlog —
  **not** a body-buffering route class (v1's `LoggingApiRoute` re-read bodies and broke on streams).
- **Auth — on by default, not a demo.** Persisting conversation history per real user is core
  functionality, not an add-on: a returning, authenticated user must see their own conversations and
  no one else's. Default implementation is **`fastapi-users`** (MIT, refresh rotation, revocation,
  password reset, OAuth) wired against the `users` table from §3.3, with `JWTBearer` + **ownership
  checks** enforced on every `conversations`/`messages` query (`user_id` scoping at the repository
  layer, not just the router). `AUTH_ENABLED=true` by default — this needs no external credential
  (the JWT secret is local), so it doesn't break offline-first boot; it just means the first API call
  is register/login, same as any real chat product. `AUTH_ENABLED=false` remains available for eval/CI
  runs that don't need identity, but is not the reference default.
- **CORS** → explicit `CORS_ALLOW_ORIGINS` list; never `*` with credentials.
- **Observability** → Langfuse (traces/cost, no-op when off) + structlog (JSON, with a
  `censor_sensitive_data` processor — *logs only*) + **Prometheus `/metrics`**
  (`prometheus-fastapi-instrumentator`). **`/health/live`** (static) and **`/health/ready`** (checks DB,
  Redis, LLM reachability).
- **Sweeper** (optional) → **Postgres advisory-lock leader election** + `FOR UPDATE SKIP LOCKED` so a
  multi-replica deploy can't double-summarize (v1 ported this bug).

### 3.10 Cache & limits (`core/limits/`, `core/cache/`)

Redis-backed and **wired, not dormant**: `slowapi` per-user/IP rate limit on `/chat`, an
`asyncio.Semaphore` concurrency cap on in-flight generations, the per-turn wall-clock budget, and a
graph-hop cap. All enabled by env (`RATE_LIMIT_PER_MIN`, etc.); off by default for local dev. See §3.13.

### 3.11 Testing & eval

- **unit** (fixture-backed, no network), **integration** (real Postgres via compose + `asgi-lifespan`).
- **eval** (LLM-judged scenarios), `-m eval`, skipped by default.
- **retrieval eval** — a golden query set scored with Recall@k / nDCG / MRR (catches RAG regressions).
- **classification/routing eval** — a confusion matrix over intents (the make-or-break for a router).
- **injection red-team** — Promptfoo/Garak cases for the guardrails.
- **CI gate (`eval-gate.yml`)** — when `config/prompts/**` or `config/behavior/**` changes, run the
  deterministic + injection subset (cheap/local model) and **gate the merge** (OWASP: regression-test
  prompt changes). Cost-incurring LLM-judge eval stays manual.

### 3.12 Security & guardrails (`core/guardrails/`) — OWASP LLM Top 10 (2026)

A `guardrails` module shaped as **input rail → LLM → output rail**, **no-op by default** (boots offline),
wired into the graph (§3.6). The structlog censor is **logs-only and is not data protection** — say so
loudly.

**Guard model — license fix from v2:** the default rail model is **`Presidio`** (PII, MIT,
independently governed under the `data-privacy-stack` org as of mid-2026 — no longer Microsoft-owned)
plus **`Granite Guardian`** (IBM, Apache-2.0, current prompt-injection-detection leaderboard leader) as
the guard/classifier model, called directly via the same injectable, OpenAI-compatible-endpoint pattern
used for the main LLM and the reranker — not through a Colang rails engine. **Llama Guard is *not* the
default** — its "Llama Community License" is not OSI-approved open source: a 700M-MAU commercial cap
beyond which Meta's grant expires, a binding Acceptable Use Policy, and mandatory "Built with Llama"
attribution + naming conditions on derivatives, all of which would transitively bind every client this
template gets forked into. It's kept as an explicit **opt-in** for teams already committed to the Llama
ecosystem, with this license callout surfaced inline wherever it's enabled. (Higher-stakes deployments
can ensemble a second, non-overlapping guard model — e.g. Granite Guardian for prompt-injection alongside
a general moderation pass — rather than relying on one classifier for everything.)

**On NeMo Guardrails specifically:** it's Apache-2.0 and still a legitimate choice, but this template does
**not** ship a pre-authored Colang flow set as the wired-in default. A starter template can responsibly
ship Python it actually tests; it can't responsibly ship an unverified `.co` rails config and call it "the
default." The guard-model call's signature (`classify(text, direction) -> RailVerdict`) is deliberately
simple enough to register as a NeMo custom action (`rails.register_action(classify, name="check_safety")`)
against a deployment's own Colang flows, for teams that want NeMo's richer multi-flow orchestration layered
on top — but that's an integration a client fork opts into with their own tested flows, not something this
template pretends to hand you pre-verified.

OWASP republished the LLM Top 10 on 2026-08-04 with a new methodology (weighted practitioner vote +
~6,600 real-world incidents) that reshuffled several ranks and added two categories:

| OWASP LLM (2026) | Mitigation in the template |
|---|---|
| **LLM01 Prompt Injection** | input rail: deterministic override/delimiter denylist + **Granite Guardian** (or opt-in Llama Guard) reject-or-mask. Treat **retrieved RAG text as untrusted** (indirect injection). |
| **LLM02 Sensitive-Info Disclosure / PII** | **Presidio** redaction on input *before storage and before the LLM*; output PII pass. |
| **LLM03 Excessive Agency** *(was LLM06:2025 — the biggest riser, driven by real agentic/tool-use incidents)* | `tool` node: least-privilege creds, an allowlist, `interrupt()` HITL for high-impact actions, hop cap. See also OWASP's companion **Top 10 for Agentic Applications**, more specific to tool-invocation risk than the base LLM list. |
| **LLM04 Supply Chain** *(new)* | pin and verify provenance of the guard/reranker/embedding models and any proxy (LiteLLM) release; see §3.13's supply-chain note. |
| **LLM05 Data and Model Poisoning** *(new)* | validate/sanitize documents at RAG ingestion (§3.8); don't trust corpus content as instruction. |
| **LLM06 Unbounded Consumption** *(was LLM10:2025, reframed around cost-asymmetry attacks)* | budgets/rate limits (§3.13). |
| **LLM10 Improper Output Handling** *(fell from LLM05:2025)* | output rail: moderation/PII before SSE; keep the abstention gate. |

### 3.13 Cost & abuse controls

- **LiteLLM proxy** (self-hosted, config-file driven → mandate-compliant) as the `OPENAI_BASE_URL`
  target: per-key/user **budgets**, **RPM/TPM** limits, **fallback** + backoff, 429 cooldown — most of
  the control plane with zero app code.
- **In-app:** `slowapi` rate limit on `/chat`, `asyncio.Semaphore` concurrency cap, per-turn
  `asyncio.wait_for` budget, graph-hop cap, explicit `max_retries`. Promote to **on by default when
  `ENVIRONMENT=prod`**.
- **LiteLLM license boundary (open-core):** the proxy's core is MIT — routing, virtual keys, basic
  budgets/spend tracking, Prometheus metrics, SSO for ≤5 users. **Paid** (`enterprise/`, BerriAI
  Subscription required): RBAC/delegated admin, audit logs, SSO beyond 5 users, automated key rotation,
  external secret-manager integrations (Vault/KMS), multi-region. Document this boundary per client up
  front — governance features like audit logs/RBAC are common asks once a client redistributes further
  to *their* customers.
- **LiteLLM supply-chain hardening (do this, not optional):** pin an exact, audited version **≥1.83.10**
  — PyPI releases 1.82.7/1.82.8 (Mar 2026) were a confirmed supply-chain compromise (credential
  harvester + K8s lateral-movement toolkit installed on package import), and a pre-auth SQL injection /
  a KEV-listed command-injection CVE in the proxy are fixed only at ≥1.83.x. Never float `latest`. Pin
  CI tooling versions too (the compromise traced back to an unpinned scanner in LiteLLM's own build).
  Firewall/disable MCP test endpoints if unused. Subscribe to LiteLLM's security advisories as an
  ongoing-maintenance item for every client deployment running this template.
- **Alternatives considered:** if a client needs materially lower proxy latency at high RPS, **Bifrost**
  (Apache-2.0, Go) benchmarks far lower per-request overhead than LiteLLM's Python proxy. If the
  open-core ambiguity above is a dealbreaker for a client, **Portkey Gateway** (Apache-2.0) folded its
  previously-paid features into the open-source repo in 2026 and has a cleaner single-license story.
  Avoid AGPLv3-licensed gateways (e.g. LLM Gateway) given this template's unrestricted-commercial-reuse
  requirement.

### 3.14 Reusing this template across multiple clients (new in v3)

v2's design principle #7 ("neutral core, domain in `examples/`") was the right instinct but left the
actual reuse mechanics unstated — this section makes them explicit, since "we'll use this for different
clients, not just the pet one" is the reason this refresh happened.

**Copy-per-client vs. shared multi-tenancy — pick deliberately, not by default.** This template assumes
**copy-per-client** (each client gets their own repo fork + their own deployment), which current
white-label-SaaS practice treats as legitimate for small client counts but explicitly *not* free — every
bugfix only helps the one client until it's backported N times. Use this decision rule:

| Choose... | When |
|---|---|
| **Copy-per-client** (default here) | Client count is small (roughly single digits); clients need hard data/compliance isolation or deep code-level customization (not just config/branding); you can sustain N parallel deployments and N-way bugfix backports. |
| **Shared multi-tenancy** | Client count is growing past that; customization is mostly config/branding rather than logic; bugfix latency across the client base starts to matter more than per-client isolation. |

**Making copy-per-client turnkey (was missing in v2):**
- **Scaffold with Copier, not a one-shot clone.** Cookiecutter (and a plain `git clone`/zip copy) has no
  update mechanism once a project is generated — a long-standing, still-unresolved gap. **Copier** stores
  `.copier-answers.yml` in the generated project and `copier update` **3-way-merges** upstream template
  changes into an already-customized client fork. This is the concrete answer to "how do bugfixes reach
  client N after they've already diverged."
- **One client-config manifest, not scattered edits.** Add `client.config.yaml` at the repo root capturing
  everything that legitimately varies per client: display name/branding/theme tokens, active `examples/`
  pack, model/provider + rate limits, RAG corpus source, feature flags. **A client fork should only ever
  touch this file plus `examples/<domain>/` — never `core/`.** This is what keeps `copier update` merges
  low-conflict, and (bonus) it's the exact shape that ports cleanly into a per-tenant config table if the
  project ever moves to shared multi-tenancy later.
- **Ship a `NEW_CLIENT_CHECKLIST.md`.** Enumerate every place a new client fork must diverge: rename,
  branding tokens, env vars, which `examples/` pack is active, DB name, deploy target, secrets — so
  standing up client N isn't tribal knowledge.

**Shared multi-tenant mode — document as an alternative deployment profile, not a rewrite.** Because the
core schema is already generic (`users/conversations/messages/documents`), this is additive, not a
redesign: add `tenant_id uuid` (FK to a new `tenants` table) to every core table including `chunks`/
embeddings; enable Postgres **Row-Level Security** (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`, closing
the table-owner bypass) with policies against `current_setting('app.tenant_id')`; set that GUC per-request
in FastAPI middleware from the resolved tenant (subdomain or JWT claim) — this scopes both relational
queries *and* pgvector similarity search inside the same transaction; move `client.config.yaml` into a
per-tenant config table/row instead of per-fork files. Treat this as the mode to switch to once the
decision rule above tips past copy-per-client's comfort zone — not something to build speculatively now.

### Appendix A — MCP (optional, off by default)

In-process `FastMCP` server + in-memory client, behind `MCP_ENABLED`, with a clean fall-through to the
direct service call. Kept as a *pattern demo* only — it buys nothing over a direct call unless you
federate external MCP clients, and it interacts badly with `astream_events` nesting. Don't enable in
prod without that need.

---

## 4. Frontend architecture (Vite + React)

A SPA — correct for an authed chat client (no SSR value). Feature-Sliced: `app → features/* → shared`;
features own component+store+hook+types+tests; barrels; `shared/` has zero business logic.

### 4.1 Layout

```
src/
├── app/ (main.tsx, App.tsx, router.tsx, providers.tsx)
├── features/chat/ (ChatContainer, MessageList, ChatInput, hooks/use-streaming-chat.ts, stores/chat-store.ts)
│         tool-artifact/  guardrail/  debug/
└── shared/api/{client,sse-parser,config}.ts  types/{sse-events(generated),index}.ts  components/ui/  lib/
```

### 4.2 The SSE pipeline (extracted & de-coupled — **not** "ported verbatim")

This hook is a **generic**, framework-agnostic parser + dispatch: no domain coupling baked in, server-issued
ids. i18n is optional (`react-i18next`).

- **Layer 1 — fetch** → `ReadableStream` (POST, `Accept: text/event-stream`).
- **Layer 2 — parser** → spec-compliant async generator (decode → buffer → blank-line dispatch → skip
  `:` heartbeats → `JSON.parse`); **surface parse failures as a typed stream error**, don't silently
  `console.warn`.
- **Layer 3 — typed dispatch** → switch on the discriminated `type`, update Zustand.
  - **Typewriter buffer** (rAF, time-based CPS, latency-bounded) — **visibility-aware**: on
    `document.hidden`, bypass rAF (direct flush / `setTimeout`) so background tabs don't freeze mid-stream
    and streams still finalize.
  - **Ordered artifact deferral** (hold a `tool_result` card until its parent text finishes typing).
  - **Resume:** on disconnect, reconnect to `GET /chat/stream/{id}?last_event_id=…`; `stopStreaming()`
    calls `POST /chat/stream/{id}/stop` (true terminate) vs a network drop (resumable).
- **a11y:** `aria-live="polite"` on the message region; honor `prefers-reduced-motion` (disable the
  typewriter).

### 4.3 State, styling, contract

- **State:** Zustand per feature, selectors for reads, `getState()` for actions. Server-state
  (conversation list/history) is better as **TanStack Query** than a Zustand store.
- **Styling:** Tailwind v4 CSS-first tokens; shadcn on `@base-ui/react` — this is now shadcn's **default**
  primitive substrate as of July 2026 (Radix, the prior default, remains supported via `-b radix` for
  existing projects). MIT-licensed, MUI-maintained, stable since Dec 2025.
- **Contract:** **`openapi-typescript` off FastAPI's `/openapi.json`** is *the* path — it preserves the
  discriminated union the dispatch relies on (which `json-schema-to-typescript` flattens) and generates
  the **full REST client** (auth/conversations) too. Requires registering the SSE event models in OpenAPI
  (§3.7). `make contract` regenerates; CI checks for drift. (`@hey-api/openapi-ts` is a current, more
  actively growing alternative if you also want generated SDK methods/TanStack Query hooks rather than
  bare types + a separate fetch client — swap in if that tradeoff is worth it for a given client.)

---

## 5. Local development

```yaml
# docker-compose.yml (sketch) — lean default
services:
  db:    { image: pgvector/pgvector:pg16, ports: ["5432:5432"], environment: {POSTGRES_USER: app, POSTGRES_PASSWORD: app, POSTGRES_DB: app} }
  redis: { image: redis:7-alpine, ports: ["6379:6379"] }
  backend:  { build: ./backend, env_file: .env, depends_on: [db, redis], ports: ["8000:8000"] }
  frontend: { build: ./frontend, ports: ["5173:80"] }
# docker-compose.langfuse.yml  → web+worker+postgres+clickhouse+redis+minio (HEAVY — opt-in)
# docker-compose.litellm.yml   → LiteLLM proxy (budgets/rate-limit/fallback) — opt-in
```

First-run is intentionally light (`LANGFUSE_ENABLED=false`, `USE_LOCAL_RETRIEVAL=true`,
`STREAM_DURABLE=false`, guardrails off). `Makefile`: `setup · run · test · up/down · migrate · seed ·
ingest · contract · up-langfuse · up-litellm`. `mise.toml` pins python/node/uv/pnpm.

`.env.example` is grouped (Core / LLM / Retrieval / Streaming / Guardrails / Limits / Auth /
Observability / Frontend) — every knob documented, safe defaults.

---

## 6. CI/CD (GitHub Actions, registry-agnostic)

- **`ci.yml`** — BE `ruff` + `ruff format --check` + `mypy` + `pytest`; FE `eslint` + `tsc` + `vitest`
  + `pnpm build`; **contract drift check** (`openapi-typescript` diff).
- **`eval-gate.yml`** — path-filtered on `config/prompts|behavior/**` → deterministic + injection eval
  on a cheap model; gates merge.
- **`docker.yml`** — multi-stage builds → **ghcr.io** (`docker/build-push-action`).
- Deploy is target-agnostic (compose/k8s/Fly/Render); images are portable.

---

## 7. Core architectural commitments

The load-bearing decisions that every later revision (v1→v2→v3) has preserved: layered
`core/modules/agents`; a DI composition root (scoped to singletons); vertical slices; provider-agnostic
`get_llm`; a deterministic-router LangGraph; contract-first SSE with the streamer kept separate from the
graph; offline-first Protocol+factory pattern; prompts/behavior as config; Langfuse + structlog; the FE
SSE pipeline, typewriter, and feature-sliced stores.

**Fixed by the v2 validation pass (see changelog above):** transactions; checkpointer-based durable
state/resume/HITL; real RAG (index/hybrid/rerank/ingestion/abstention); resumable streams; security
rails; cost controls; the response-envelope/`BaseHTTPMiddleware` removed; a local runtime-control plane;
a neutral core; corrected streaming technique; sweeper leader-election; pagination/idempotency/readiness/
metrics. Several of these were carried uncritically from the v1 draft — v2 applied the same scrutiny to
them that v1 applied to eliminating the cloud-config dependency in the first place.

---

## 8. Scaffold plan (phase 2 — build order)

Each step independently runnable/testable:

1. **Repo skeleton** — monorepo dirs, `mise.toml`, `.env.example`, `Makefile`, `.gitignore`, `copier.yml`
   (template variables) + `client.config.yaml` (§3.14) so every client fork starts from a Copier-managed
   base, not a one-shot copy.
2. **Backend foundation** — `pyproject.toml` (uv), ruff/mypy, `core/config.py` + `runtime_config.py`,
   `core/db`, Alembic init + first migration (**pgvector extension + HNSW + tsvector + tables +
   `config_overrides`**), `main.py` (lean lifespan, exception handlers, pure-ASGI request-id,
   Prometheus), `health` (live+ready). → probes + `/metrics` work.
3. **Persistence + DI + transactions** — `BaseRepository` (CRUD + pagination), `conversations`/`messages`
   modules with explicit commit/rollback, the container (incl. `sessionmaker`, checkpointer). → CRUD +
   conversation REST, transactional.
4. **Prompts/behavior + runtime control** — `PromptEngine` (file + Langfuse overlay + `watchfiles`),
   sample `config/`.
5. **Agents** — `llm.py` (LiteLLM-aware, retries), graph compiled **with `AsyncPostgresSaver`**, the
   nodes (incl. rails hooks, hop cap, fallback ladder); `embedding` + **hybrid `retrieval`** + reranker
   (+ local fixture); **`ingestion` CLI**. → graph runs offline via CLI; `make ingest` populates chunks.
6. **Streaming endpoint** — `sse.py` (id-stamped), `core/stream/resume.py` (Redis bus), `chat_stream.py`
   (custom-writer streaming, session-per-turn UoW, idempotency), simple + durable modes,
   resume/stop endpoints. → `POST /chat` streams; reconnect resumes.
7. **Guardrails + limits** — `core/guardrails` (no-op default + Presidio/Granite Guardian hooks, NeMo Guardrails registerable-not-bundled, Llama Guard opt-in only),
   `core/limits` (slowapi + semaphore + budget), auth (wired/optional). → safe to expose.
8. **Frontend** — Vite scaffold, generic `shared/api` (client + parser + resume), `openapi-typescript`
   contract, `features/chat` (visibility-aware hook + store + components), a11y, one Playwright happy
   path. → end-to-end chat in the browser.
9. **Glue** — compose files (lean + langfuse + litellm), Dockerfiles, `ci.yml` / `eval-gate.yml` /
   `docker.yml`, `make contract`, `NEW_CLIENT_CHECKLIST.md` (§3.14).
10. **Eval** — minimal scenario + retrieval + routing + injection packs (skipped/path-gated).

**Acceptance:** `make up && make ingest` → open the frontend → send a message → streamed,
typewriter-rendered, grounded reply with citations; kill the network mid-stream → reconnect resumes the
same turn — all with `USE_LOCAL_RETRIEVAL` optional and **no external credentials required**.
