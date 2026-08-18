// Regression test for a store-initialization race (found in production,
// not caught by any existing test): `persist`'s `onRehydrateStorage`
// callback can fire synchronously *inside* `create(...)`, before the
// `export const useAuthStore = create(...)` assignment below it has
// completed -- so a naive implementation that calls `useAuthStore.setState`
// (or anything that transitively does) from that callback reads `useAuthStore`
// as `undefined` and throws `Cannot read properties of undefined (reading
// 'setState')` on literally every page load. This module is re-imported
// fresh per test (`vi.resetModules()`) so `create(...)` -- and the
// rehydration race it can trigger -- actually re-runs each time, the same
// way it does on a real page load.

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

    // The bug reproduces synchronously (or on the very next microtask) --
    // this call itself is the assertion that nothing threw during module
    // init. Flush a microtask afterward so `restoreSession`'s deferred
    // `queueMicrotask` callback has actually run before we assert state.
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
