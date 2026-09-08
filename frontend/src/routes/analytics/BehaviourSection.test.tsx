import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { BehaviourSection } from "./BehaviourSection";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

test("renders flows, efficiency (long-route badge), and model usage", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const p = new URL(String(url), "http://x").pathname;
    if (p === "/insights/flows")
      return json([{ flow: "LLM → TOOL → LLM", n_traces: 67, avg_steps: 3, avg_tokens: 735, example_prompt: "why break" }]);
    if (p === "/insights/efficiency")
      return json([
        { representative: "recon break", count: 35, route_len_avg: 4.2, baseline_route: 1.5, long_route: true, opportunity_score: 900 },
      ]);
    if (p === "/insights/models")
      return json([{ model: "us.anthropic.claude-sonnet-4-6", n_calls: 198, total_tokens: 154980, total_cost_usd: 1.04, avg_latency_ms: 3518, error_rate: 0.035 }]);
    return new Response("[]", { status: 200 });
  });

  renderWithProviders(<BehaviourSection id="fobo" />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() => expect(screen.getByText("LLM → TOOL → LLM")).toBeInTheDocument());
  expect(screen.getByText("long")).toBeInTheDocument();
  expect(screen.getByText("claude-sonnet-4-6")).toBeInTheDocument();
  expect(screen.getByText("Agent flows")).toBeInTheDocument();
});
