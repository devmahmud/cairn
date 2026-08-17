# Cairn

*A durable, checkpointed foundation for building agent chat apps — the marker that always knows the way back.*

Cairn is a reusable, **open-source, self-hostable** template for production-grade streaming LLM/agent
chat applications. FastAPI + LangGraph on the backend, Vite + React on the frontend, Postgres + pgvector
for everything (rows, vectors, full-text) — no Microsoft/Azure dependency, no cloud config service, and
no license traps: every component is checked for OSI-approved terms before it's a default.

Full architecture, design rationale, and the phase-2 build order live in **[BLUEPRINT.md](./BLUEPRINT.md)**.
Standing up a new client deployment from this template? Start with **[NEW_CLIENT_CHECKLIST.md](./NEW_CLIENT_CHECKLIST.md)**.

## Status

Blueprint v3, validated. Scaffold build in progress.

## License

MIT — see [LICENSE](./LICENSE).
