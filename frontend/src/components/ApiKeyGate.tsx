import { type ReactNode, useEffect, useState } from "react";
import { ApiError, api, apiKey, setApiKey } from "@/api/client";

type GateState = "checking" | "open" | "locked";

export function ApiKeyGate({ children }: { children: ReactNode }) {
  const [key, setKey] = useState(apiKey() ?? "");
  const [state, setState] = useState<GateState>(() => (apiKey() ? "open" : "checking"));
  const [authRequired, setAuthRequired] = useState(false);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    if (apiKey()) return;
    let cancelled = false;
    (async () => {
      try {
        // /health is always open; probe a protected route to detect auth.
        await api.get("/capabilities");
        if (!cancelled) setState("open");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setAuthRequired(true);
        } else if (!(err instanceof ApiError)) {
          // Network / CORS / DNS — API never answered.
          setUnreachable(true);
        }
        // Auth, network, or other errors: show the form.
        setState("locked");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "open") return <>{children}</>;

  if (state === "checking") {
    return (
      <p className="mx-auto mt-24 max-w-sm text-center text-sm text-muted-foreground">
        Connecting…
      </p>
    );
  }

  return (
    <form
      className="mx-auto mt-24 max-w-sm space-y-3 rounded-lg border border-border bg-card p-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (authRequired && !key.trim()) return;
        setApiKey(key || null);
        setState("open");
      }}
    >
      <h1 className="text-lg font-semibold">Phoenix</h1>
      <p className="text-sm text-muted-foreground">
        {authRequired
          ? "This API requires an X-API-Key."
          : unreachable
            ? "Can't reach the API. Start it on :8000, then refresh — or leave blank to continue anyway."
            : "Enter the API key, or leave blank if the server runs open on localhost."}
      </p>
      <input
        aria-label="API key"
        type="password"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        required={authRequired}
      />
      <button
        type="submit"
        className="w-full rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground hover:opacity-90"
      >
        Continue
      </button>
    </form>
  );
}
