// Cairn frontend — auth store (BLUEPRINT.md §4.1, §4.3, §8 step 8).
//
// Zustand, persisted (tokens only, `localStorage`) so a page reload doesn't
// force a re-login. Registers itself into `shared/api/auth-session.ts`'s
// `AuthSession` seam once at module load -- *before* anything can call
// `authorizedFetch` -- so `client.ts` never imports this store (or Zustand)
// directly (§4's "`shared/` has zero business logic").

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { setAuthSession } from "@/shared/api/auth-session";
import { ApiError, getMe, login as apiLogin, logout as apiLogout, registerUser } from "@/shared/api/client";
import type { components } from "@/shared/types/api";

type User = components["schemas"]["UserRead"];
type AuthStatus = "idle" | "authenticating" | "ready" | "unauthenticated";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  status: AuthStatus;
  error: string | null;
}

interface AuthActions {
  register(email: string, password: string): Promise<void>;
  login(email: string, password: string): Promise<void>;
  logout(): Promise<void>;
  clearError(): void;
}

type AuthStore = AuthState & AuthActions;

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong. Please try again.";
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      status: "idle",
      error: null,

      async register(email, password) {
        set({ status: "authenticating", error: null });
        try {
          await registerUser({ email, password });
        } catch (err) {
          set({ status: "unauthenticated", error: messageOf(err) });
          throw err;
        }
        await get().login(email, password);
      },

      async login(email, password) {
        set({ status: "authenticating", error: null });
        try {
          const pair = await apiLogin({ email, password });
          set({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
          const user = await getMe();
          set({ user, status: "ready" });
        } catch (err) {
          set({
            accessToken: null,
            refreshToken: null,
            user: null,
            status: "unauthenticated",
            error: messageOf(err),
          });
          throw err;
        }
      },

      async logout() {
        const { refreshToken } = get();
        set({ accessToken: null, refreshToken: null, user: null, status: "unauthenticated", error: null });
        if (refreshToken) {
          await apiLogout(refreshToken).catch(() => {
            // Best-effort revocation -- the tokens are already cleared
            // client-side either way, so a network failure here shouldn't
            // block the user from appearing logged out.
          });
        }
      },

      clearError() {
        set({ error: null });
      },
    }),
    {
      name: "cairn.auth",
      partialize: (state) => ({ accessToken: state.accessToken, refreshToken: state.refreshToken }),
      onRehydrateStorage: () => (state) => {
        void restoreSession(state);
      },
    },
  ),
);

async function restoreSession(state: AuthStore | undefined): Promise<void> {
  if (!state?.accessToken) {
    useAuthStore.setState({ status: "unauthenticated" });
    return;
  }
  useAuthStore.setState({ status: "authenticating" });
  try {
    const user = await getMe();
    useAuthStore.setState({ user, status: "ready" });
  } catch {
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      user: null,
      status: "unauthenticated",
    });
  }
}

setAuthSession({
  getAccessToken: () => useAuthStore.getState().accessToken,
  getRefreshToken: () => useAuthStore.getState().refreshToken,
  setTokens: ({ accessToken, refreshToken }) => useAuthStore.setState({ accessToken, refreshToken }),
  clearTokens: () =>
    useAuthStore.setState({ accessToken: null, refreshToken: null, user: null, status: "unauthenticated" }),
});
