// Cairn frontend — Vite config (BLUEPRINT.md §4, §8 step 8).
//
// Vite 8 ships Rolldown as its default bundler and a built-in tsconfig-paths
// resolver (`resolve.tsconfigPaths`) — no `vite-tsconfig-paths` plugin, that
// would just duplicate what Vite already does natively now. The `@/*` alias
// resolved here comes straight from `tsconfig.app.json`'s `paths`, one
// source of truth for both the editor and the bundler.
//
// `defineConfig` comes from `vitest/config`, not `vite`, so the `test` key
// below type-checks against Vitest's `InlineConfig` merged into Vite's own
// `UserConfig` — one config file for both the dev/build and test runner.

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    tsconfigPaths: true,
  },
  server: {
    port: 5173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/shared/lib/test-setup.ts"],
    css: true,
    exclude: ["**/node_modules/**", "**/e2e/**", "**/dist/**"],
  },
});
