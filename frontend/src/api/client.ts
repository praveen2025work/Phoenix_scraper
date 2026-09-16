// Prefer 127.0.0.1 over localhost (IPv4-only API binds).
// Unset VITE_API_BASE → http://<page-hostname>:8000 (works on LAN).

const API_PORT = "8000";

/** Resolve the API base URL for the current browser page. */
export function resolveApiBase(
  envBase: string | undefined = import.meta.env.VITE_API_BASE,
  hostname: string | undefined = typeof window !== "undefined"
    ? window.location.hostname
    : undefined,
): string {
  const configured = (envBase || "").trim();
  if (configured) return configured.replace(/\/$/, "");
  const host = (hostname || "127.0.0.1").trim() || "127.0.0.1";
  const apiHost = host === "localhost" ? "127.0.0.1" : host;
  return `http://${apiHost}:${API_PORT}`;
}

const BASE = resolveApiBase();
const KEY = "skillgap_api_key";
const LEGACY_KEY = "pheonix_api_key";

export function apiKey(): string | null {
  try {
    return sessionStorage.getItem(KEY) ?? sessionStorage.getItem(LEGACY_KEY);
  } catch {
    return null;
  }
}

export function setApiKey(value: string | null): void {
  try {
    sessionStorage.removeItem(LEGACY_KEY);
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
