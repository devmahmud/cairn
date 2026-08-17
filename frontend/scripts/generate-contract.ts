// Cairn — `make contract` / `pnpm run contract` (BLUEPRINT.md §4.3, §8 step 8).
//
// One script, two jobs:
//   1. `pnpm run contract`       -- regenerate `src/shared/types/api.ts` in place.
//   2. `pnpm run contract:check` (`--check`) -- regenerate into memory and diff
//      against the committed file; exits non-zero on drift (wired into CI,
//      BLUEPRINT.md §8 step 9).
//
// "Starts nothing": dumping the schema only imports `main.app` and calls
// `app.openapi()` (`backend/scripts/dump_openapi.py`) -- no live Postgres,
// Redis, or LLM credential required, the same fact BLUEPRINT.md §8 step 8
// calls out explicitly. `src/shared/types/api.ts` is the one file this
// script owns; `src/shared/types/sse-events.ts` is a small hand-written
// wrapper over its `components['schemas']['ChatSSEEvent']` (its own module
// docstring explains why that split, not a second generated file, is the
// right shape here) -- don't hand-edit `api.ts` itself, it's overwritten
// every run.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString, COMMENT_HEADER, type OpenAPI3 } from "openapi-typescript";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const BACKEND_ROOT = path.resolve(FRONTEND_ROOT, "..", "backend");
const OUTPUT_PATH = path.join(FRONTEND_ROOT, "src", "shared", "types", "api.ts");

function dumpOpenApiSchema(): OpenAPI3 {
  let raw: string;
  try {
    raw = execFileSync("uv", ["run", "python", "scripts/dump_openapi.py"], {
      cwd: BACKEND_ROOT,
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024,
    });
  } catch (err) {
    const stderr = err instanceof Error && "stderr" in err ? String(err.stderr) : "";
    throw new Error(
      `Failed to dump the backend's OpenAPI schema (backend/scripts/dump_openapi.py).\n${stderr}`,
      { cause: err },
    );
  }
  return JSON.parse(raw) as OpenAPI3;
}

async function generate(): Promise<string> {
  const schema = dumpOpenApiSchema();
  const ast = await openapiTS(schema, { alphabetize: true });
  return `${COMMENT_HEADER}${astToString(ast)}`;
}

async function main(): Promise<void> {
  const checkOnly = process.argv.includes("--check");
  const generated = await generate();

  if (!checkOnly) {
    writeFileSync(OUTPUT_PATH, generated, "utf8");
    console.log(`Wrote ${path.relative(FRONTEND_ROOT, OUTPUT_PATH)}`);
    return;
  }

  if (!existsSync(OUTPUT_PATH)) {
    console.error(`${OUTPUT_PATH} does not exist -- run \`pnpm run contract\` first.`);
    process.exitCode = 1;
    return;
  }
  const committed = readFileSync(OUTPUT_PATH, "utf8");
  if (committed !== generated) {
    console.error(
      "Contract drift detected: the backend's OpenAPI schema no longer matches the " +
        "committed src/shared/types/api.ts. Run `pnpm run contract` and commit the result.",
    );
    process.exitCode = 1;
    return;
  }
  console.log("Contract is up to date.");
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
});
