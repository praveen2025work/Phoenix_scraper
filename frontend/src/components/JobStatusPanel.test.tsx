import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { JobStatusPanel } from "./JobStatusPanel";

function wrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockJobs(rows: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/capabilities/fobo/jobs/") && url.endsWith("/cancel")) {
        return new Response(
          JSON.stringify({
            job_id: "j1",
            state: "error",
            run_id: null,
            error: "cancelled",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (
        url.endsWith("/capabilities/fobo/jobs") &&
        (!init?.method || init.method === "GET")
      ) {
        return new Response(JSON.stringify(rows), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("not found", { status: 404 });
    }),
  );
}

test("lists queued/running/done jobs with stage and actions", async () => {
  mockJobs([
    {
      job_id: "j-run",
      state: "running",
      stage: "scraping",
      progress: 0.2,
      message: "Pulling spans",
      run_id: null,
      error: null,
      enqueued_at: "2026-09-15T12:00:00Z",
    },
    {
      job_id: "j-done",
      state: "done",
      stage: "done",
      progress: 1,
      message: "ok",
      run_id: "2026-09-14T10:00:00+00:00",
      error: null,
      enqueued_at: "2026-09-14T09:00:00Z",
    },
  ]);
  const onWatch = vi.fn();
  const onOpen = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <JobStatusPanel
      capabilityId="fobo"
      activeJobId="j-run"
      onWatchJob={onWatch}
      onOpenRun={onOpen}
    />,
    { wrapper: wrapper(qc) },
  );

  await waitFor(() =>
    expect(screen.getByTestId("job-status-panel")).toBeInTheDocument(),
  );
  expect(screen.getByText(/Pulling spans/i)).toBeInTheDocument();
  expect(screen.getByText(/scraping/i)).toBeInTheDocument();

  await userEvent.click(screen.getByTestId("job-open-j-done"));
  expect(onOpen).toHaveBeenCalledWith("2026-09-14T10:00:00+00:00");

  await userEvent.click(screen.getByTestId("job-watch-j-run"));
  expect(onWatch).toHaveBeenCalledWith("j-run");
});

test("empty state when no jobs yet", async () => {
  mockJobs([]);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<JobStatusPanel capabilityId="fobo" />, { wrapper: wrapper(qc) });
  await waitFor(() =>
    expect(screen.getByTestId("job-status-empty")).toBeInTheDocument(),
  );
  expect(screen.getByText(/No jobs yet/i)).toBeInTheDocument();
});

test("cancel action posts cancel for a running job", async () => {
  mockJobs([
    {
      job_id: "j1",
      state: "running",
      stage: "analyzing",
      progress: 0.5,
      message: "Clustering",
      run_id: null,
      error: null,
      enqueued_at: "2026-09-15T12:00:00Z",
    },
  ]);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<JobStatusPanel capabilityId="fobo" />, { wrapper: wrapper(qc) });
  await waitFor(() => expect(screen.getByTestId("job-cancel-j1")).toBeInTheDocument());
  await userEvent.click(screen.getByTestId("job-cancel-j1"));
  await waitFor(() => {
    const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
    expect(
      calls.some(
        ([u, init]) =>
          String(u).includes("/jobs/j1/cancel") &&
          String((init as RequestInit | undefined)?.method ?? "").toUpperCase() ===
            "POST",
      ),
    ).toBe(true);
  });
});
