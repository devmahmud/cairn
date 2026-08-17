// Cairn frontend — the one Playwright happy path (BLUEPRINT.md §8 step 8).
//
// Register -> land in `/chat` (this app's `register()` action logs in right
// after registering, `features/auth/stores/auth-store.ts`) -> start a new
// conversation -> send a message -> see a streamed assistant reply render.
//
// Needs a real, reachable backend -- there is no mocked-backend mode here on
// purpose (§3.11's own integration-test bar: prove the real path works, not
// a stand-in for it). Point `PLAYWRIGHT_API_BASE_URL` at one, migrated and
// running with `AUTH_ENABLED=true`:
//
//   cd backend
//   DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app_e2e \
//     uv run alembic upgrade head
//   DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app_e2e \
//     USE_LOCAL_RETRIEVAL=true AUTH_ENABLED=true JWT_SECRET=e2e-test-secret \
//     CORS_ALLOW_ORIGINS=http://localhost:4173 \
//     uv run uvicorn main:app --app-dir src --port 8000
//   cd ../frontend && PLAYWRIGHT_API_BASE_URL=http://localhost:8000 pnpm test:e2e
//
// A reachable model provider is *not* required: BLUEPRINT.md's own
// acceptance bar for the backend includes graceful degradation when the LLM
// call itself fails (an `error` SSE event immediately followed by a normal
// `message_delta`/`message_end` carrying a friendly fallback message, per
// `agents/chat/nodes/rag.py` and `modules/chat/chat_stream.py`) -- this test
// only asserts that *some* assistant reply renders, not any particular text,
// so it passes in both a real-model and a no-model local run.

import { expect, test } from "@playwright/test";

test("register, start a conversation, send a message, see a streamed reply", async ({ page }) => {
  const email = `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`;
  const password = "correct horse battery staple";

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /create account/i }).click();

  await page.waitForURL(/\/chat$/);

  await page.getByRole("button", { name: /new conversation/i }).click();
  await page.waitForURL(/\/chat\/[0-9a-f-]{36}$/);

  const input = page.getByRole("textbox", { name: /message/i });
  await input.fill("Hello, what can you help with?");
  await input.press("Enter");

  await expect(page.getByTestId("chat-message-user").last()).toContainText(
    "Hello, what can you help with?",
  );

  const assistantBubble = page.getByTestId("chat-message-assistant").last();
  await expect(assistantBubble).toBeVisible({ timeout: 30_000 });
  await expect(async () => {
    const text = (await assistantBubble.textContent())?.trim() ?? "";
    expect(text.length).toBeGreaterThan(0);
  }).toPass({ timeout: 30_000 });

  // The turn eventually finishes (typewriter drains, `data-pending` clears) --
  // proves the stream reached a real terminal state, not just "some text
  // showed up and then the page silently stalled".
  await expect(assistantBubble).not.toHaveAttribute("data-pending", "true", { timeout: 30_000 });
});
