import { getAuthSession } from "./auth-session";
import { API_BASE_URL } from "./config";
import type { components } from "@/shared/types/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type AppErrorBody = { error: { code: string; detail: string } };
type HttpExceptionBody = { detail: string | Record<string, string> };
type ValidationErrorBody = { detail: components["schemas"]["ValidationError"][] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function extractErrorMessage(response: Response): Promise<{ message: string; code?: string }> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { message: response.statusText || `Request failed (${response.status})` };
  }

  if (isRecord(body) && isRecord((body as Partial<AppErrorBody>).error)) {
    const { error } = body as AppErrorBody;
    return { message: error.detail, code: error.code };
  }

  if (isRecord(body) && "detail" in body) {
    const { detail } = body as HttpExceptionBody | ValidationErrorBody;
    if (typeof detail === "string") return { message: detail };
    if (Array.isArray(detail)) {
      return { message: detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("; ") };
    }
    if (isRecord(detail)) return { message: Object.values(detail).join("; ") };
  }

  return { message: response.statusText || `Request failed (${response.status})` };
}

async function throwForStatus(response: Response): Promise<never> {
  const { message, code } = await extractErrorMessage(response);
  throw new ApiError(response.status, message, code);
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) await throwForStatus(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function buildUrl(path: string, query?: Record<string, string | number | undefined | null>): URL {
  const url = new URL(path, API_BASE_URL);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  return url;
}

// --- Unauthenticated calls ---------------------------------------------

export async function registerUser(payload: {
  email: string;
  password: string;
}): Promise<components["schemas"]["UserRead"]> {
  const body: components["schemas"]["UserCreate"] = {
    email: payload.email,
    password: payload.password,
    is_active: true,
    is_superuser: false,
    is_verified: false,
  };
  const response = await fetch(buildUrl("/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson(response);
}

export async function login(payload: {
  email: string;
  password: string;
}): Promise<components["schemas"]["TokenPair"]> {
  const form = new URLSearchParams({ username: payload.email, password: payload.password });
  const response = await fetch(buildUrl("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  return parseJson(response);
}

export async function refreshTokens(
  refreshToken: string,
): Promise<components["schemas"]["TokenPair"]> {
  const response = await fetch(buildUrl("/auth/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  return parseJson(response);
}

export async function logout(refreshToken: string): Promise<void> {
  const response = await fetch(buildUrl("/auth/logout"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok && response.status !== 404) await throwForStatus(response);
}

// --- Authenticated calls -------------------------------------------------

let refreshInFlight: Promise<boolean> | null = null;

// Module-level, so concurrent 401s coalesce onto one in-flight refresh instead of each firing their own.
function refreshOnce(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    const session = getAuthSession();
    const refreshToken = session?.getRefreshToken();
    if (!session || !refreshToken) return false;
    try {
      const pair = await refreshTokens(refreshToken);
      session.setTokens({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
      return true;
    } catch {
      session.clearTokens();
      return false;
    }
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

// On a 401, refreshes once and retries the request exactly once with the new token.
export async function authorizedFetch(
  path: string,
  init: RequestInit & { query?: Record<string, string | number | undefined | null> } = {},
): Promise<Response> {
  const { query, ...rest } = init;
  const url = buildUrl(path, query);

  const doFetch = (): Promise<Response> => {
    const token = getAuthSession()?.getAccessToken();
    const headers = new Headers(rest.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(url, { ...rest, headers });
  };

  const first = await doFetch();
  if (first.status !== 401) return first;

  const refreshed = await refreshOnce();
  if (!refreshed) return first;
  return doFetch();
}

export async function getMe(): Promise<components["schemas"]["UserRead"]> {
  return parseJson(await authorizedFetch("/auth/me"));
}

export async function listConversations(params: {
  cursor?: string | null;
  limit?: number;
} = {}): Promise<components["schemas"]["ConversationPage"]> {
  const response = await authorizedFetch("/conversations", {
    query: { cursor: params.cursor ?? undefined, limit: params.limit },
  });
  return parseJson(response);
}

export async function createConversation(payload: {
  title?: string | null;
}): Promise<components["schemas"]["ConversationRead"]> {
  const response = await authorizedFetch("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload satisfies components["schemas"]["ConversationCreate"]),
  });
  return parseJson(response);
}

export async function listMessages(
  conversationId: string,
  params: { cursor?: string | null; limit?: number } = {},
): Promise<components["schemas"]["MessagePage"]> {
  const response = await authorizedFetch(`/conversations/${conversationId}/messages`, {
    query: { cursor: params.cursor ?? undefined, limit: params.limit },
  });
  return parseJson(response);
}

const STREAM_ID_HEADER = "X-Stream-Id";

export async function startChatTurn(payload: {
  conversationId: string;
  text: string;
  idempotencyKey: string;
  signal?: AbortSignal;
}): Promise<Response> {
  const body: components["schemas"]["ChatTurnRequest"] = {
    conversation_id: payload.conversationId,
    text: payload.text,
    idempotency_key: payload.idempotencyKey,
  };
  return authorizedFetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal: payload.signal,
  });
}

export function readStreamId(response: Response): string | null {
  return response.headers.get(STREAM_ID_HEADER);
}

export async function resumeChatStream(params: {
  streamId: string;
  lastEventId: string | null;
  signal?: AbortSignal;
}): Promise<Response> {
  return authorizedFetch(`/chat/stream/${params.streamId}`, {
    headers: { Accept: "text/event-stream" },
    query: { last_event_id: params.lastEventId ?? undefined },
    signal: params.signal,
  });
}

export async function stopChatStream(streamId: string): Promise<void> {
  const response = await authorizedFetch(`/chat/stream/${streamId}/stop`, { method: "POST" });
  if (!response.ok && response.status !== 404) await throwForStatus(response);
}
