import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Analytics } from "./Analytics";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

test("renders KPIs, coverage rows, and run deltas scoped to the capability", async () => {
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = new URL(String(url), "http://x");
    const p = u.pathname + u.search;
    if (p === "/overview?capability=fobo")
      return json({ n_spans: 120, n_users: 4, error_rate: 0.1 });
    if (p === "/skills/coverage?capability=fobo")
      return json([{ skill_name: "fobo-triage", count: 30, n_declared_examples: 2, covered: true }]);
    if (p === "/capabilities/fobo/runs/delta")
      return json([{ status: "growing", count_prev: 10, count: 25, representative: "why break" }]);
    return new Response("null", { status: 404 });
  });

  renderWithProviders(<Analytics />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() => expect(screen.getByText("120")).toBeInTheDocument());
  expect(screen.getByText("fobo-triage")).toBeInTheDocument();
  expect(screen.getByText("growing")).toBeInTheDocument();
  expect(spy.mock.calls.some(([u]) => String(u).includes("capability=fobo"))).toBe(true);
});

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });
