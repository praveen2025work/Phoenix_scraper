import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useJob } from "./hooks";

afterEach(() => vi.restoreAllMocks());

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

function wrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

test("useJob polls until the job is terminal, then stops", async () => {
  let calls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
    calls += 1;
    return json({ state: calls >= 2 ? "done" : "running", run_id: "r1", error: null });
  });

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { result } = renderHook(() => useJob("plex", "job-1", 40), { wrapper: wrapper(qc) });

  await waitFor(() => expect(result.current.data?.state).toBe("done"));
  const settled = calls;
  await new Promise((r) => setTimeout(r, 200));
  expect(calls).toBe(settled); // no further polls once 'done'
});

test("useJob is disabled when jobId is null", () => {
  const spy = vi.spyOn(globalThis, "fetch");
  const qc = new QueryClient();
  renderHook(() => useJob("plex", null), { wrapper: wrapper(qc) });
  expect(spy).not.toHaveBeenCalled();
});
