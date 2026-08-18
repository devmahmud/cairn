// Seam so client.ts (shared/) never imports the auth store (features/) directly; the store registers itself here at init.

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
