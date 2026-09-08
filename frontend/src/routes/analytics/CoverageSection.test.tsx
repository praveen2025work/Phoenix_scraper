import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { CoverageSection } from "./CoverageSection";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

test("renders a row from each panel and expands the paste block", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const p = new URL(String(url), "http://x").pathname;
    if (p === "/skills/coverage")
      return json([{ skill_name: "fobo-triage", count: 30, n_declared_examples: 2, covered: true }]);
    if (p === "/skills/updates")
      return json([
        { skill_name: "fobo-triage", source_file: "x.yaml", n_new_prompts: 1, uncovered_asks: 6, n_users: 3, yaml_block: "example_prompts:\n  - why break" },
      ]);
    if (p === "/skills/gaps")
      return json([{ proposed_name: "list-breaks", level: "capability", capability: "fobo", evidence_count: 15, representative_prompt: "list unmatched trades" }]);
    if (p === "/insights/skill-health")
      return json([{ skill_name: "fobo-triage", n_asks: 35, avg_route_len: 1.4, error_rate: 0.03, status: "effective" }]);
    return new Response("[]", { status: 200 });
  });

  renderWithProviders(<CoverageSection id="fobo" />, { route: "/c/fobo/analytics", path: "/c/:id/analytics" });
  await waitFor(() => expect(screen.getByText("list-breaks")).toBeInTheDocument());
  expect(screen.getByText("Skill coverage")).toBeInTheDocument();
  expect(screen.getByText("effective")).toBeInTheDocument();

  await userEvent.click(screen.getByText(/show block/i));
  expect(screen.getByText(/example_prompts:/)).toBeInTheDocument();
});
