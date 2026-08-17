// Cairn frontend — the auth/client seam (BLUEPRINT.md §4.1, §8 step 8).
//
// `shared/` has zero business logic (§4's Feature-Sliced rule), so
// `client.ts` can't import `features/auth/stores/auth-store.ts` directly --
// that would be a `shared -> features` dependency, backwards from every
// other edge in this tree. Instead, the auth store registers itself here
// once, at module init, behind this tiny interface; `client.ts` only ever
// talks to `AuthSession`, never to Zustand or the store's own action names.

export interface AuthSession {
  getAccessToken(): string | null;
  getRefreshToken(): string | null;
  setTokens(tokens: { accessToken: string; refreshToken: string }): void;
  clearTokens(): void;
}

let session: AuthSession | null = null;

export function setAuthSession(next: AuthSession): void {
  session = next;
}

export function getAuthSession(): AuthSession | null {
  return session;
}
