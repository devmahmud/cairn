// Registers into auth-session.ts's AuthSession seam at module load, so shared/api/client.ts never imports this store directly.

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
          // Best-effort: tokens are already cleared client-side regardless.
          await apiLogout(refreshToken).catch(() => {});
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
        // Deferred: rehydration fires synchronously inside this create(...) call, before the useAuthStore binding below exists.
        queueMicrotask(() => {
          void restoreSession(state);
        });
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
