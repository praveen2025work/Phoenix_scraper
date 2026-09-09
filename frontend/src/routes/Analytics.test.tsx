import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Analytics } from "./Analytics";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

function mock(routes: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = new URL(String(url), "http://x");
    const hit = routes[u.pathname + u.search] ?? routes[u.pathname];
    return hit === undefined ? new Response("[]", { status: 200 }) : json(hit);
  });
}

test("headline: KPIs + activity chart + run deltas render scoped to the capability", async () => {
  const spy = mock({
    "/overview?capability=fobo": {
      n_spans: 388,
      n_users: 8,
      error_rate: 0.02,
      total_cost_usd: 1.1,
    },
    "/quality/overview?capability=fobo": { span_pass_rate: 0.89, n_failed_spans: 42 },
    "/insights/activity?capability=fobo": [
      { day: "2026-09-06", n_asks: 12, total_cost_usd: 0.1 },
      { day: "2026-09-07", n_asks: 20, total_cost_usd: 0.2 },
    ],
    "/capabilities/fobo/runs/delta": [
      { status: "growing", count_prev: 10, count: 25, representative: "why break" },
    ],
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() => expect(screen.getByText("388")).toBeInTheDocument());
  expect(screen.getByText("89%")).toBeInTheDocument();
  expect(screen.getByText("growing")).toBeInTheDocument();
  // every /insights and /quality call is scoped
  const scopedOk = spy.mock.calls.every(([u]) => {
    const s = String(u);
    return !/\/(insights|quality|overview)/.test(s) || s.includes("capability=fobo");
  });
  expect(scopedOk).toBe(true);
});

test("the period every panel describes is stated, not left to be guessed", async () => {
  // These numbers are the last run's window, which is what the API now scopes to.
  mock({
    "/capabilities/fobo": {
      summary: {
        id: "fobo",
        name: "FOBO",
        window_days: 30,
        last_run: {
          run_id: "2026-09-09T10:00:00+00:00",
          window_start: "2026-08-01T00:00:00+00:00",
          window_end: "2026-09-05T00:00:00+00:00",
        },
      },
    },
    "/overview?capability=fobo": { n_spans: 388 },
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });

  await waitFor(() =>
    expect(screen.getByText(/2026-08-01.*2026-09-05/)).toBeInTheDocument(),
  );
});

test("with no run yet, the fallback period is named as such", async () => {
  mock({
    "/capabilities/fobo": {
      summary: { id: "fobo", name: "FOBO", window_days: 30, last_run: null },
    },
  });
  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });

  await waitFor(() => expect(screen.getByText(/last 30 days/i)).toBeInTheDocument());
});
