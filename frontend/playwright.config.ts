// Cairn frontend — Playwright config (BLUEPRINT.md §8 step 8).
//
// Needs a real backend (Postgres-backed, `AUTH_ENABLED=true`) reachable at
// `PLAYWRIGHT_API_BASE_URL` (default `http://localhost:8000`) -- there is no
// mocked-backend mode here on purpose, this suite exists to prove the real
// register -> login -> create-conversation -> streamed-chat-turn path works
// end to end, the same acceptance bar as the backend's own integration tests
// (BLUEPRINT.md §3.11). `webServer` starts the frontend's own preview server;
// it does *not* start the backend -- see `e2e/happy-path.spec.ts`'s
// module docstring for how to stand one up locally.

import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // `import.meta.env.VITE_API_BASE_URL` is inlined at *build* time, not
    // read at serve time -- `vite preview` alone would keep serving
    // whatever origin the last `pnpm build` happened to bake in, ignoring
    // `env` below. Building here, right before preview, is what makes
    // `PLAYWRIGHT_API_BASE_URL` actually take effect.
    command: `pnpm build && pnpm exec vite preview --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      VITE_API_BASE_URL: process.env.PLAYWRIGHT_API_BASE_URL ?? "http://localhost:8000",
    },
  },
});
