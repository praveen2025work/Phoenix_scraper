const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const KEY = "pheonix_api_key";

export function apiKey(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setApiKey(value: string | null): void {
  try {
    if (value) sessionStorage.setItem(KEY, value);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* private mode / blocked storage — the header just won't be sent */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

export async function fetchJson<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const key = apiKey();
  if (key) headers.set("X-API-Key", key);
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      /* body not json */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(p: string) => fetchJson<T>(p),
  post: <T>(p: string, body?: unknown) =>
    fetchJson<T>(p, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(p: string, body: unknown) =>
    fetchJson<T>(p, { method: "PATCH", body: JSON.stringify(body) }),
  del: <T>(p: string) => fetchJson<T>(p, { method: "DELETE" }),
};
