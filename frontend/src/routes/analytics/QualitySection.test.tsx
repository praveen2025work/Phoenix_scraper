import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { QualitySection } from "./QualitySection";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

test("renders scoreboard, a quality chart, and failed spans", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = new URL(String(url), "http://x");
    const p = u.pathname + u.search;
    if (p === "/quality/checks?capability=fobo")
      return json([
        { check: "answer_relevance", target: "output", n_evaluated: 243, n_failed: 13, fail_rate: 0.05, example: "off topic" },
      ]);
    if (p === "/quality/by?dimension=user_id&capability=fobo")
      return json([{ user_id: "analyst-1", n_spans: 40, fail_rate: 0.1, top_issues: "output_empty (2)" }]);
    if (p === "/quality/by?dimension=model_name&capability=fobo")
      return json([{ model_name: "us.anthropic.claude-sonnet-4-6", n_spans: 100, fail_rate: 0.03, top_issues: "" }]);
    if (p === "/quality/by-prompt?capability=fobo")
      return json([{ representative: "why break", count: 35, span_fail_rate: 0.2, top_issues: "x", priority: 28 }]);
    if (p === "/quality/failures?top=25&capability=fobo")
      return json([{ span_id: "fixture-050-05-llm", user_id: "analyst-1", model_name: "a.b.sonnet", workflow_stage: "commentary_signoff", failed_checks: "answer_relevance" }]);
    return new Response("[]", { status: 200 });
  });

  renderWithProviders(<QualitySection id="fobo" />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() =>
    expect(screen.getAllByText("answer_relevance").length).toBeGreaterThanOrEqual(1),
  );
  expect(screen.getByText("Validation scoreboard")).toBeInTheDocument();
  expect(screen.getByText("Answer quality by user")).toBeInTheDocument();
  expect(screen.getByText("Answer quality by model")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText(/050-05-llm/)).toBeInTheDocument());
});
