# Cairn frontend — multi-stage, pnpm-based image (BLUEPRINT.md §5, §6, §8 step 8).
#
# Build stage installs deps from the committed lockfile (`--frozen-lockfile`
# fails the build on drift, instead of silently re-resolving) and produces a
# static `dist/` via `vite build`; the runtime stage is a bare nginx serving
# that output, so the final image carries no Node, no `pnpm`, and no
# `node_modules`. `VITE_API_BASE_URL` is a *build-time* arg -- Vite inlines
# `import.meta.env.*` at build time, so it must be supplied to `docker build`
# (`--build-arg`) for a given deployment's backend origin, not left to be
# read at container-start (§5's `.env.example` documents the same variable
# for local `pnpm dev`).

FROM node:24-alpine AS builder

# Pinned to the same pnpm major as mise.toml (§5).
RUN corepack enable && corepack prepare pnpm@10 --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm build


FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
