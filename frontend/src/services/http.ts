/** Authenticated HTTP client: in-memory access token, silent refresh via the HttpOnly cookie. */
let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<() => void>();

export function setAccessToken(token: string | null): void { accessToken = token; }
export function onSessionExpired(fn: () => void): () => void { listeners.add(fn); return () => listeners.delete(fn); }

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/v1/auth/refresh", {
      method: "POST", credentials: "same-origin",
      headers: { "X-Refresh-Request-ID": crypto.randomUUID() },
    }).then(async (r) => {
      if (!r.ok) return false;
      setAccessToken(((await r.json()) as { access_token: string }).access_token);
      return true;
    }).catch(() => false).finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function detail(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (typeof body?.detail === "string") return body.detail;
  if (response.status === 403) return "Your role does not permit this action.";
  return `Request failed (${response.status})`;
}

export async function apiFetch(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError("Cannot reach the AVA backend. Check that the API server is running.", 0);
  }
  if (response.status === 401 && retry && !path.startsWith("/api/v1/auth/")) {
    if (await refreshSession()) return apiFetch(path, init, false);
    listeners.forEach((fn) => fn());
  }
  return response;
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) throw new ApiError(await detail(response), response.status);
  return (await response.json()) as T;
}

/** Single-use, 30-second ticket for a WebSocket or SSE stream bound to `sessionId`. */
export async function streamTicket(sessionId: string): Promise<string> {
  const data = await apiJson<{ ticket: string }>("/api/v1/auth/ws-ticket", { method: "POST", body: JSON.stringify({ session_id: sessionId }) });
  return data.ticket;
}
