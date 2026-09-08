import { type ReactNode, useState } from "react";
import { apiKey, setApiKey } from "@/api/client";

export function ApiKeyGate({ children }: { children: ReactNode }) {
  const [key, setKey] = useState(apiKey() ?? "");
  const [entered, setEntered] = useState(!!apiKey());

  if (entered) return <>{children}</>;

  return (
    <form
      className="mx-auto mt-24 max-w-sm space-y-3 rounded-lg border border-border bg-card p-6"
      onSubmit={(e) => {
        e.preventDefault();
        setApiKey(key || null);
        setEntered(true);
      }}
    >
      <h1 className="text-lg font-semibold">pheonix</h1>
      <p className="text-sm text-muted-foreground">
        Enter the API key, or leave blank if the server runs open on localhost.
      </p>
      <input
        aria-label="API key"
        type="password"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
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
