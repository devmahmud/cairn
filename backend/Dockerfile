# Cairn backend — multi-stage, uv-based image (BLUEPRINT.md §5, §6, §8 step 2).
#
# Build stage resolves/installs dependencies into a project-local venv with
# `uv sync --locked` (fails the build if `uv.lock` drifts from
# `pyproject.toml`, instead of silently re-resolving); the runtime stage
# copies only that venv + source, so the final image carries no `uv`, no
# build toolchain, and no wheel cache.

FROM python:3.13-slim AS builder

# Pinned to the same uv minor version as mise.toml (§5).
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev


FROM python:3.13-slim AS runtime

# `langgraph-checkpoint-postgres` pulls in `psycopg` (v3, not `asyncpg`, per
# `core/db/engine.py::to_psycopg_dsn`'s docstring) as a *pure* dependency --
# no `[binary]`/`[c]` extra is pinned in `pyproject.toml`, so `psycopg` falls
# back to its ctypes bindings against the system `libpq`, which
# `python:3.13-slim` does not ship. Without this, `AsyncPostgresSaver`'s
# import chain (`core/db/checkpointer.py`, reached from `main.py` at module
# load, before the lifespan even runs) fails with "no pq wrapper available"
# and the container never starts. `libpq5` alone (not the much larger
# `libpq-dev`/`postgresql-client`) is the minimal runtime shared library.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --create-home app

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/alembic ./alembic
COPY --from=builder /app/alembic.ini ./alembic.ini
COPY --from=builder /app/config ./config
COPY --from=builder /app/docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

USER app

EXPOSE 8000

# Runs `alembic upgrade head` before exec'ing the CMD below (§5, §8 step 9) --
# `docker-compose.yml` relies on this so a fresh `docker compose up` on an
# empty Postgres volume ends up with a working schema, not a manual-migrate
# step. `docker run <image> <other-cmd>` (e.g. a one-off shell) still
# migrates first too, since the entrypoint wraps every CMD, not just this one.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
