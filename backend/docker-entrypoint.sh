#!/bin/sh
# Cairn backend container entrypoint (BLUEPRINT.md §5, §8 step 9).
#
# Runs Alembic migrations before handing off to the container's CMD (a
# plain `exec "$@"`), so `docker compose up` against a brand-new Postgres
# volume -- or a bare `docker run` of the published ghcr.io image -- always
# ends up with a migrated schema, never a "relation does not exist" 500 on
# the first request. Idempotent: `alembic upgrade head` against an
# already-current database is a no-op, so this is safe to run on every
# container start, not just the first.
#
# Deliberately does NOT wait for Postgres to be reachable itself --
# `docker-compose.yml` already gates the backend service's startup on the
# `db` service's healthcheck (`depends_on: condition: service_healthy`), so
# by the time this script runs under compose, Postgres is already accepting
# connections. A bare `docker run` outside compose against an unreachable
# database fails loudly here instead, which is the correct behavior.
set -eu

echo "cairn-backend: applying Alembic migrations..."
alembic upgrade head

echo "cairn-backend: starting: $*"
exec "$@"
