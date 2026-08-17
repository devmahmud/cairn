# New Client Checklist

Everything a new client fork of Cairn should touch on its way to a real deployment. Per
[BLUEPRINT.md §3.14](./BLUEPRINT.md#314-reusing-this-template-across-multiple-clients-new-in-v3), a
client fork should only ever diverge on **`client.config.yaml`** plus **`backend/src/examples/<pack>/`**
— never hand-edit `core/`. That's what keeps `copier update` able to 3-way-merge upstream fixes into an
already-customized fork later. Everything below either *is* one of those two places, or is an
env var/secret/infra knob that legitimately lives outside version control.

Work through this top to bottom before your first real (non-`localhost`) deployment. Nothing here is
optional scaffolding — an unchecked item is either a broken client experience or a leaked default
credential.

## 1. Scaffold the fork

- [ ] `copier copy gh:<org>/cairn <client-repo>` (not a plain `git clone`/zip copy — Copier writes
      `.copier-answers.yml` into the new repo, which is what lets `copier update` merge upstream fixes
      later instead of you hand-porting every bugfix).
- [ ] Answer the `copier.yml` prompts deliberately, not with the defaults:
      `project_name`, `client_display_name`, `client_slug`, `active_example_pack`, `database_name`,
      `openai_model`, `use_auth`, `use_guardrails`, `use_langfuse`, `docker_registry`.
- [ ] Confirm `.copier-answers.yml` was written and commit it — the client fork's `.gitignore` excludes
      it *from the template repo* (this repo, intentionally — it's not meaningful here), but a generated
      client fork needs it committed for `copier update` to work.

## 2. Project rename

- [ ] `client.config.yaml` → `client.display_name`, `client.slug`, `client.description`.
- [ ] `frontend/index.html`'s `<title>` (currently `Cairn`).
- [ ] `backend/src/main.py`'s `FastAPI(title=..., description=...)`.
- [ ] `README.md`'s title/pitch, and this file's own references if you rename `NEW_CLIENT_CHECKLIST.md`.
- [ ] Docker image names / compose `name:` if you want them client-branded rather than `cairn-*`.

## 3. Branding tokens

- [ ] `client.config.yaml`'s `branding` block: `theme.primary_color`, `theme.accent_color`.
- [ ] `theme.logo_path` / `theme.favicon_path` point at
      `frontend/src/shared/assets/logo.svg` / `frontend/public/favicon.svg` — **these files don't exist
      in the template as shipped** (no default logo/favicon is bundled); create them for your client and
      wire them into `frontend/index.html` and wherever the frontend renders a logo (currently no
      component does — add one alongside your branding pass).
- [ ] Tailwind v4 CSS-first tokens (`frontend/src/app/index.css`) if the client's palette needs more than
      the two accent colors above (typography, spacing, dark-mode tokens).

## 4. Which `examples/` pack is active

- [ ] `client.config.yaml`'s `examples.active_pack` — `docs-assistant` (the neutral worked example this
      template ships) or your own new pack under `backend/src/examples/<your-domain>/`.
- [ ] If you're building a new domain pack: follow the strippable-pack pattern (BLUEPRINT.md §2, §7) —
      domain-specific slots/entities/routing tables live under `examples/`, never in `core/` or
      `modules/`. `backend/src/examples/` is empty (just `.gitkeep`) until a pack needs real code there.
- [ ] Prompts: `backend/config/prompts/docs_assistant/*.j2` → rename/replace the directory to match your
      active pack, and update `core/prompts/` callers/tests that reference the `docs_assistant` path.
- [ ] Sample corpus: `backend/data/sample_corpus/*.md` → replace with (or add alongside) your client's
      real ingestible content, then re-run `make ingest`.
- [ ] Behavior config: `backend/config/behavior/routing.yaml` (intents/routes), `retrieval.yaml`,
      `guardrails.yaml` — these are hot-reloaded (`watchfiles`, §3.2), no redeploy needed once running,
      but review them for anything `docs-assistant`-specific before go-live.

## 5. Database

- [ ] `client.config.yaml`'s `deployment.database_name` and `.env`'s `DATABASE_URL` — a distinct DB name
      per client if you're not fully isolating at the Postgres-instance level.
- [ ] If adopting **shared multi-tenant mode** instead of copy-per-client (BLUEPRINT.md §3.14's decision
      rule — only once client count/bugfix-backport pain outgrows copy-per-client): add `tenant_id`,
      enable Postgres RLS, and move `client.config.yaml` into a per-tenant config table. Don't do this
      speculatively for client #1.
- [ ] Run `make migrate` (or let the backend container's entrypoint do it — see `docker-compose.yml`) and
      confirm `alembic upgrade head` is clean against the client's real Postgres before first traffic.

## 6. Env vars & secrets — generate real values, don't ship placeholders

Every item below has a **placeholder, offline-first default** in `.env.example` specifically so the
template boots with zero credentials. That default is correct for local dev and **wrong** for anything a
real user or the public internet can reach. Regenerate/collect real values for:

- [ ] `JWT_SECRET` — `openssl rand -hex 32`. The app **fails to boot** with the placeholder once
      `ENVIRONMENT != local` (fail-fast, §3.2) — you will not forget this one by accident, but set it
      deliberately rather than relying on the crash to remind you.
- [ ] `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` — the client's real LLM provider, or point
      `OPENAI_BASE_URL` at your own LiteLLM proxy (`make up-litellm`) / self-hosted Ollama/vLLM.
- [ ] `DATABASE_URL` — real host/user/password for the client's Postgres, not `app:app@localhost`.
- [ ] `CORS_ALLOW_ORIGINS` — the client's real frontend origin(s). **Never `*`** — the app fails a startup
      check if it finds a wildcard here while `allow_credentials=True` (it always is).
- [ ] `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` / `RERANKER_BASE_URL` / `RERANKER_MODEL` — if you're
      pointing at real self-hosted embedding/reranker endpoints instead of `USE_LOCAL_RETRIEVAL=true`'s
      zero-dep fixture. Changing `EMBEDDING_DIMENSION` needs a new Alembic migration (the `chunks.embedding`
      column width is fixed at migration time, §3.3) — decide this before ingesting real client data, not
      after.
- [ ] `GUARDIAN_MODEL_BASE_URL` (Granite Guardian) if `use_guardrails`/`GUARDRAILS_ENABLED=true` — blank
      silently degrades to denylist+PII only. If the client specifically wants Llama Guard instead, read
      `core/guardrails/llama_guard.py`'s docstring first: its license is **not OSI-approved** (700M-MAU
      commercial cap, binding AUP, mandatory attribution) — get sign-off before enabling
      `GUARDRAILS_LLAMA_GUARD_OPT_IN=true` on a client engagement.
- [ ] `LITELLM_MASTER_KEY` — required if using `docker-compose.litellm.yml`; the proxy won't start
      without a real one. Also review `backend/litellm.config.yaml`'s `model_list` for the client's real
      upstream model(s) and, if the client will redistribute further to *their* own customers, read
      BLUEPRINT.md §3.13's LiteLLM open-core boundary (RBAC/audit-log/SSO-beyond-5-users/secret-manager
      integrations are paid `enterprise/`) before promising those features.
- [ ] `LANGFUSE_*` (`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST`) if `use_langfuse=true` —
      from the client's own Langfuse project (`make up-langfuse`, then create a project + API key at
      `http://localhost:3000` or wherever you deploy it).
- [ ] If deploying `docker-compose.langfuse.yml` beyond a throwaway local instance: replace its
      placeholder `SALT` / `ENCRYPTION_KEY` / `NEXTAUTH_SECRET` / Postgres+MinIO credentials — every one of
      them is a labeled local-dev-only value in that file, not something to run in production as-is.
- [ ] `RATE_LIMIT_PER_MIN` / `MAX_CONCURRENT_GENERATIONS` / `MAX_GRAPH_HOPS` / `TURN_BUDGET_SECONDS` —
      tune to the client's actual traffic/cost tolerance; all default to permissive/off for local dev
      (§5). BLUEPRINT.md §3.13 recommends promoting these on by default once `ENVIRONMENT=prod`.
- [ ] Store all of the above in your real secrets manager (SOPS+age, cloud secrets manager, CI secrets) —
      never commit a filled-in `.env`. `.gitignore` already excludes `.env` (keeping `.env.example`
      tracked); don't work around that.

## 7. Auth / SSO

- [ ] `AUTH_ENABLED` should stay `true` for any client-facing deployment (§3.9 — this isn't a demo toggle;
      turning it off drops per-user conversation ownership). It's only meant to be `false` for eval/CI
      runs that don't need identity.
- [ ] The template ships `fastapi-users` email+password (register/login/refresh/logout) — **no OAuth/SSO
      provider is wired by default.** If the client needs Google/Microsoft/SAML/OIDC login,
      `fastapi-users` supports OAuth backends natively; that integration (client ID/secret, callback URLs,
      `modules/auth/router.py` additions) is client-specific work this checklist flags but doesn't do for
      you.
- [ ] Rotate `ACCESS_TOKEN_LIFETIME_SECONDS` / `REFRESH_TOKEN_LIFETIME_SECONDS` if the client has specific
      session-length requirements.

## 8. Deploy target

- [ ] Images are registry-agnostic and portable (BLUEPRINT.md §6) — `docker-compose.yml` is the local/
      reference deployment; pick the client's real target (compose on a single box, k8s, Fly, Render,
      ECS, ...) and adapt from there. Nothing in `backend/`/`frontend/` assumes a specific host.
- [ ] `docker_registry` in `copier.yml`'s answers / `client.config.yaml`'s `deployment.docker_registry` —
      if not `ghcr.io`, update `.github/workflows/docker.yml`'s login step (currently `ghcr.io` +
      `GITHUB_TOKEN`, which needs no extra secret only because it's GitHub's own registry) with the new
      registry's login action/credentials.
- [ ] `frontend/Dockerfile`'s `VITE_API_BASE_URL` build arg — must be supplied at `docker build` time
      (Vite inlines `import.meta.env.*` at build, not at container start) with the client's real backend
      origin for that environment.
- [ ] Healthchecks (`/health/live`, `/health/ready`) are already wired for compose; confirm your target's
      own orchestrator (k8s liveness/readiness probes, ALB target group, etc.) points at the same paths
      rather than reinventing them.

## 9. Verify before go-live

- [ ] `docker compose config` validates cleanly against the client's real `.env`.
- [ ] `make up && make migrate && make ingest` (or your deploy target's equivalent) comes up healthy on a
      **fresh** database — this is the same bar the base template itself is held to (BLUEPRINT.md §8's
      acceptance criterion), and it's the first thing that breaks if a client-specific env var was missed.
- [ ] Register → login → create a conversation → send a message, through the real deployed frontend, not
      just `curl`/Postman against the backend.
- [ ] Cross-user ownership isolation still holds (a second user gets 404, not 403 or someone else's data,
      on a conversation they don't own) — this is core behavior, not something client customization should
      ever be able to weaken.
- [ ] `make contract-check` is clean (no drift between the backend's OpenAPI schema and the committed
      frontend types) before shipping any backend change that touches request/response/SSE shapes.
