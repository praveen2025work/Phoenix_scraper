import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { RunResultsChrome } from "./RunResults";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const RUN_ID = "2026-09-08T10:00:00+00:00";

const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), {
    status,
    headers: { "content-type": "application/json" },
  });

const resultsBody = {
  capability_id: "fobo",
  run_id: RUN_ID,
  status: "ok",
  window_start: "2026-09-01T00:00:00+00:00",
  window_end: "2026-09-08T00:00:00+00:00",
  notes: [],
  warnings: [],
  skill_hashes: { "fobo-break-triage.md": "abcd".repeat(16) },
  funnel: {
    n_spans: 100,
    n_in_scope_spans: 40,
    n_clusters: 3,
    n_uncovered: 1,
    n_unmatched: 0,
    n_rung1_candidates: 1,
    n_rung2_candidates: 0,
    empty_at: null,
    empty_reason: null,
  },
  uncovered: [],
  suggested_skill_updates: [],
  rung1_candidates: [],
  rung2_candidates: [],
};

function mockApis(opts: { analyticsReady: boolean }) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = new URL(String(url), "http://x");
    if (u.pathname.endsWith("/results")) {
      return json({ ...resultsBody, analytics_ready: opts.analyticsReady });
    }
    if (u.pathname === "/capabilities/fobo/runs") {
      // Simulate history cap: current run absent from the list.
      return json([]);
    }
    if (u.pathname === "/capabilities/fobo") {
      return json({
        summary: {
          id: "fobo",
          name: "FOBO",
          last_run: {
            run_id: "some-other-run",
            analytics_ready: false,
          },
        },
      });
    }
    return json([]);
  });
}

test("Usage is disabled for failed run without analytics_ready", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = new URL(String(url), "http://x");
    if (u.pathname.endsWith("/results")) {
      return json({ ...resultsBody, status: "failed", analytics_ready: false });
    }
    if (u.pathname === "/capabilities/fobo/runs") return json([]);
    return json([]);
  });
  renderWithProviders(
    <RunResultsChrome capabilityId="fobo" runId={RUN_ID} onRunNext={() => {}} />,
  );
  const btn = await screen.findByTestId("usage-button");
  expect(btn).toBeDisabled();
  expect(btn).toHaveAttribute("title", "Available after a run finishes");
  expect(btn.tagName).toBe("BUTTON");
});

test("Usage enables for ok run even without analytics_ready (live fallback)", async () => {
  mockApis({ analyticsReady: false });
  renderWithProviders(
    <RunResultsChrome capabilityId="fobo" runId={RUN_ID} onRunNext={() => {}} />,
  );
  const btn = await screen.findByTestId("usage-button");
  await waitFor(() => expect(btn).not.toBeDisabled());
  expect(btn).toHaveAttribute("href", "/c/fobo/analytics");
});

test("Usage is an enabled outline button linking to analytics when ready", async () => {
  mockApis({ analyticsReady: true });
  renderWithProviders(
    <RunResultsChrome capabilityId="fobo" runId={RUN_ID} onRunNext={() => {}} />,
  );
  const btn = await screen.findByTestId("usage-button");
  await waitFor(() => expect(btn).not.toBeDisabled());
  expect(btn).toHaveAttribute("href", "/c/fobo/analytics");
  expect(btn).toHaveTextContent(/^Usage$/);
});
