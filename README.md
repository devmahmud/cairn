# Cairn

*A durable, checkpointed foundation for building agent chat apps — the marker that always knows the way back.*

Cairn is a reusable, **open-source, self-hostable** template for production-grade streaming LLM/agent
chat applications. FastAPI + LangGraph on the backend, Vite + React on the frontend, Postgres + pgvector
for everything — rows, vectors, and full-text search in one store. Durable by default: the agent loop
checkpoints at every step, so a dropped connection or a restart resumes right where it left off.

**New to this repo? Start with [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — a clear, as-built
overview of how the running system actually works: the request/streaming flow, the LangGraph agent, RAG,
auth, guardrails, and a map of what lives where.

Design rationale, the license-audit trail, and the phase-2 build order that produced this codebase live
in **[BLUEPRINT.md](./BLUEPRINT.md)** (a decision log, not an onboarding doc). Standing up a new client
deployment from this template? Start with **[NEW_CLIENT_CHECKLIST.md](./NEW_CLIENT_CHECKLIST.md)**.

## Status

Blueprint v3, validated. Scaffold build in progress.

## License

MIT — see [LICENSE](./LICENSE).
