// Regression test (see onRehydrateStorage in auth-store.ts); re-imports fresh per test so the race actually re-runs.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getMe = vi.fn();

vi.mock("@/shared/api/client", () => ({
  ApiError: class ApiError extends Error {},
  getMe: (...args: unknown[]) => getMe(...args),
  login: vi.fn(),
  logout: vi.fn(),
  registerUser: vi.fn(),
}));

async function importFreshStore() {
  vi.resetModules();
  return import("./auth-store");
}

describe("useAuthStore rehydration", () => {
  beforeEach(() => {
    localStorage.clear();
    getMe.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not throw and settles to unauthenticated with no stored session", async () => {
    const { useAuthStore } = await importFreshStore();

    // Flush the deferred queueMicrotask before asserting state.
    await Promise.resolve();

    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(getMe).not.toHaveBeenCalled();
  });

  it("restores a real session from a stored token without throwing", async () => {
    localStorage.setItem(
      "cairn.auth",
      JSON.stringify({ state: { accessToken: "tok", refreshToken: "rtok" }, version: 0 }),
    );
    getMe.mockResolvedValue({ id: "u1", email: "user@example.com" });

    const { useAuthStore } = await importFreshStore();
    await vi.waitFor(() => expect(useAuthStore.getState().status).toBe("ready"));

    expect(useAuthStore.getState().user).toEqual({ id: "u1", email: "user@example.com" });
    expect(getMe).toHaveBeenCalledTimes(1);
  });

  it("clears a stored token that no longer resolves, without throwing", async () => {
    localStorage.setItem(
      "cairn.auth",
      JSON.stringify({ state: { accessToken: "stale", refreshToken: "stale-r" }, version: 0 }),
    );
    getMe.mockRejectedValue(new Error("401"));

    const { useAuthStore } = await importFreshStore();
    await vi.waitFor(() => expect(useAuthStore.getState().status).toBe("unauthenticated"));

    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});
