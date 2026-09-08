import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { CapabilityDetail } from "./CapabilityDetail";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const capBody = {
  capability: { id: "fobo", name: "FOBO", status: "active", filter: {}, window_days: 30 },
  summary: {
    id: "fobo",
    name: "FOBO",
    status: "active",
    filter: { workflow_stage: "fobo_recon" },
    window_days: 30,
    last_run: {
      run_id: "2026-09-08T10:00:00+00:00",
      status: "ok",
      n_spans: 100,
      n_in_scope_spans: 40,
      n_clusters: 3,
      n_rung1_candidates: 1,
      n_rung2_candidates: 0,
      notes: [],
    },
    candidates: {},
  },
  skill_files: [],
};

function mock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const p = new URL(String(url), "http://x").pathname;
    if (p === "/capabilities/fobo") return json(capBody);
    if (p === "/capabilities/fobo/candidates")
      return json([
        {
          candidate_id: "fobo:s:a",
          capability_id: "fobo",
          rung: "skill",
          subtype: "new_skill",
          status: "ready",
          title: "why recon break",
          matched_skill: null,
          current_evidence: { count: 40, n_users: 6 },
          cluster_id: "a",
        },
      ]);
    if (p === "/capabilities/fobo/jobs" && init?.method === "POST")
      return json({ job_id: "job-1", state: "queued" });
    if (p === "/capabilities/fobo/jobs/job-1")
      return json({ state: "done", run_id: "2026-09-08T11:00:00+00:00", error: null });
    return new Response("null", { status: 404 });
  });
}
const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

test("renders the header, run summary, and the two rung tabs", async () => {
  mock();
  renderWithProviders(<CapabilityDetail />, { route: "/c/fobo", path: "/c/:id" });
  await waitFor(() => expect(screen.getByText(/\/ FOBO/)).toBeInTheDocument());
  expect(screen.getByText(/workflow_stage=fobo_recon/)).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /Rung 1/i })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /Rung 2/i })).toBeInTheDocument();
  expect(screen.getByText("why recon break")).toBeInTheDocument();
});

test("Run now enqueues a background job and polls it", async () => {
  const spy = mock();
  renderWithProviders(<CapabilityDetail />, { route: "/c/fobo", path: "/c/:id" });
  await waitFor(() => screen.getByRole("button", { name: /run now/i }));
  await userEvent.click(screen.getByRole("button", { name: /run now/i }));
  await waitFor(() =>
    expect(
      spy.mock.calls.some(
        ([u, i]) =>
          String(u).endsWith("/capabilities/fobo/jobs") &&
          (i as RequestInit).method === "POST",
      ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(spy.mock.calls.some(([u]) => String(u).includes("/jobs/job-1"))).toBe(true),
  );
});
