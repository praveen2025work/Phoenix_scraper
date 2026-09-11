import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Analytics } from "./Analytics";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const RUN_ID = "2026-09-09T10:00:00+00:00";

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

function mock(routes: Record<string, unknown>, status: Record<string, number> = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = new URL(String(url), "http://x");
    const key = u.pathname + u.search;
    const hit = routes[key] ?? routes[u.pathname];
    const code = status[key] ?? status[u.pathname] ?? 200;
    if (hit === undefined && code === 200) {
      return new Response("[]", { status: 200 });
    }
    if (code >= 400) {
      return new Response(JSON.stringify({ detail: "not ready" }), {
        status: code,
        headers: { "content-type": "application/json" },
      });
    }
    return json(hit);
  });
}

const snapshotPanels = {
  overview: {
    n_spans: 388,
    n_users: 8,
    error_rate: 0.02,
    total_cost_usd: 1.1,
  },
  quality_overview: { span_pass_rate: 0.89, n_failed_spans: 42 },
  activity: [
    { day: "2026-09-06", n_asks: 12, total_cost_usd: 0.1 },
    { day: "2026-09-07", n_asks: 20, total_cost_usd: 0.2 },
  ],
  delta: [
    { status: "growing", count_prev: 10, count: 25, representative: "why break" },
  ],
  skills_coverage: [],
  skills_updates: [],
  skills_gaps: [],
  skill_health: [],
  questions: [],
  quality_checks: [],
  quality_by_user_id: [],
  quality_by_model_name: [],
  quality_by_prompt: [],
  quality_failures: [],
  flows: [],
  efficiency: [],
  breakdown: [],
  tools: [],
  models: [],
  users: [],
};

test("headline: KPIs + activity + deltas render from the run snapshot", async () => {
  const spy = mock({
    "/capabilities/fobo": {
      summary: {
        id: "fobo",
        name: "FOBO",
        window_days: 30,
        last_run: {
          run_id: RUN_ID,
          analytics_ready: true,
          window_start: "2026-08-01T00:00:00+00:00",
          window_end: "2026-09-05T00:00:00+00:00",
        },
      },
    },
    [`/capabilities/fobo/runs/${encodeURIComponent(RUN_ID)}/analytics`]: {
      capability_id: "fobo",
      run_id: RUN_ID,
      window_start: "2026-08-01T00:00:00+00:00",
      window_end: "2026-09-05T00:00:00+00:00",
      panels: snapshotPanels,
    },
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() => expect(screen.getByText("388")).toBeInTheDocument());
  expect(screen.getByText("89%")).toBeInTheDocument();
  expect(screen.getByText("growing")).toBeInTheDocument();
  expect(screen.getByTestId("analytics-chrome")).toContainElement(
    screen.getByTestId("analytics-glance"),
  );
  // Snapshot path — no live /overview or /insights fan-out
  const liveCalls = spy.mock.calls.filter(([u]) =>
    /\/(overview|insights|quality)\b/.test(String(u)),
  );
  expect(liveCalls).toHaveLength(0);
});

test("the period every panel describes is stated, not left to be guessed", async () => {
  mock({
    "/capabilities/fobo": {
      summary: {
        id: "fobo",
        name: "FOBO",
        window_days: 30,
        last_run: {
          run_id: RUN_ID,
          analytics_ready: true,
          window_start: "2026-08-01T00:00:00+00:00",
          window_end: "2026-09-05T00:00:00+00:00",
        },
      },
    },
    [`/capabilities/fobo/runs/${encodeURIComponent(RUN_ID)}/analytics`]: {
      capability_id: "fobo",
      run_id: RUN_ID,
      panels: { overview: { n_spans: 388 } },
    },
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });

  await waitFor(() =>
    expect(screen.getByText(/2026-08-01.*2026-09-05/)).toBeInTheDocument(),
  );
  expect(screen.getByTestId("analytics-chrome")).toBeInTheDocument();
  expect(screen.getByText(/2026-08-01 → 2026-09-05 \(this version's window\)/)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Usage for this version/i })).toBeInTheDocument();
  expect(screen.queryByText(/How to use this page/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/Cost, quality/i)).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByTestId("analytics-glance")).toBeInTheDocument());
  expect(screen.getByTestId("analytics-chrome")).toContainElement(
    screen.getByTestId("analytics-glance"),
  );
});

test("with no run yet, the fallback period is named and Usage waits", async () => {
  mock({
    "/capabilities/fobo": {
      summary: { id: "fobo", name: "FOBO", window_days: 30, last_run: null },
    },
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });

  await waitFor(() => expect(screen.getByText(/last 30 days/i)).toBeInTheDocument());
  expect(screen.getByTestId("analytics-waiting")).toBeInTheDocument();
});

test("without analytics_ready but completed run, uses live panels", async () => {
  mock({
    "/capabilities/fobo": {
      summary: {
        id: "fobo",
        name: "FOBO",
        window_days: 30,
        last_run: {
          run_id: RUN_ID,
          status: "partial",
          analytics_ready: false,
          window_start: "2026-08-01T00:00:00+00:00",
          window_end: "2026-09-05T00:00:00+00:00",
        },
      },
    },
    "/overview": { n_spans: 3, n_sessions: 1, n_users: 1 },
    "/quality/overview": { span_pass_rate: 1 },
    "/insights/activity": [],
    "/capabilities/fobo/runs/delta": [],
    "/skills/coverage": [],
    "/skills/updates": [],
    "/skills/gaps": [],
    "/insights/skill-health": [],
    "/insights/questions": [],
    "/quality/checks": [],
    "/quality/by-prompt": [],
    "/insights/flows": [],
    "/insights/efficiency": [],
    "/insights/breakdown": [],
    "/insights/tools": [],
    "/insights/models": [],
    "/users": [],
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() =>
    expect(screen.queryByTestId("analytics-waiting")).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("heading", { name: /Usage for this version/i })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /At a glance/i })).not.toBeInTheDocument();
  expect(screen.getByTestId("analytics-glance")).toBeInTheDocument();
  expect(screen.getByTestId("analytics-chrome")).toContainElement(
    screen.getByTestId("analytics-glance"),
  );
});

test("without analytics_ready on failed run, shows waiting", async () => {
  mock({
    "/capabilities/fobo": {
      summary: {
        id: "fobo",
        name: "FOBO",
        window_days: 30,
        last_run: { run_id: RUN_ID, status: "failed", analytics_ready: false },
      },
    },
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() => expect(screen.getByTestId("analytics-waiting")).toBeInTheDocument());
});
