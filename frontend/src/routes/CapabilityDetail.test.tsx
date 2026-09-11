import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { CapabilityDetail } from "./CapabilityDetail";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const RUN_ID = "2026-09-08T10:00:00+00:00";
const PREV_RUN = "2026-09-07T10:00:00+00:00";
const OLDER_RUN = "2026-09-01T10:00:00+00:00";

const capBody = {
  capability: {
    id: "fobo",
    name: "FOBO",
    status: "active",
    filter: { project: "pnl-agent", workflow_stage: "fobo_recon" },
    window_days: 30,
  },
  summary: {
    id: "fobo",
    name: "FOBO",
    status: "active",
    filter: { project: "pnl-agent", workflow_stage: "fobo_recon" },
    window_days: 30,
    last_run: {
      run_id: RUN_ID,
      status: "ok",
      n_spans: 100,
      n_in_scope_spans: 40,
      n_clusters: 3,
      n_rung1_candidates: 1,
      n_rung2_candidates: 0,
      notes: [],
      analytics_ready: true,
    },
    candidates: {},
  },
  skill_files: ["fobo-break-triage.md"],
};

const resultsBody = {
  capability_id: "fobo",
  run_id: RUN_ID,
  status: "ok",
  window_start: "2026-09-01T00:00:00+00:00",
  window_end: "2026-09-08T00:00:00+00:00",
  notes: [],
  warnings: ["TRUNCATED: scrape hit limit"],
  skill_hashes: { "fobo-break-triage.md": "abcd".repeat(16) },
  analytics_ready: true,
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
  uncovered: [
    {
      cluster_id: "c1",
      representative: "why is recon break unmatched",
      count: 12,
      n_users: 4,
      source_file: "fobo-break-triage.md",
      status: "new",
    },
  ],
  suggested_skill_updates: [
    {
      skill_name: "fobo-break-triage",
      source_file: "fobo-break-triage.md",
      uncovered_asks: 12,
      n_users: 4,
      n_new_prompts: 1,
      new_prompts: ["why is recon break unmatched"],
      new_keywords: ["unmatched"],
    },
  ],
  rung1_candidates: [
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
  ],
  rung2_candidates: [],
  previous_run_id: PREV_RUN,
};

const olderResultsBody = {
  ...resultsBody,
  run_id: OLDER_RUN,
  status: "partial",
  previous_run_id: null,
  uncovered: [
    {
      cluster_id: "c-old",
      representative: "older uncovered ask",
      count: 3,
      n_users: 1,
      status: "new",
    },
  ],
  suggested_skill_updates: [],
  rung1_candidates: [],
  warnings: [],
};

const compareBody = {
  capability_id: "fobo",
  from_run: {
    run_id: PREV_RUN,
    window_start: null,
    window_end: null,
    skill_hashes: { "fobo-break-triage.md": "old".repeat(16) },
    n_gaps: 3,
  },
  to_run: {
    run_id: RUN_ID,
    window_start: null,
    window_end: null,
    skill_hashes: { "fobo-break-triage.md": "abcd".repeat(16) },
    n_gaps: 1,
  },
  skill_hash_changes: {
    added: [],
    removed: [],
    changed: [
      {
        filename: "fobo-break-triage.md",
        from: "old".repeat(16),
        to: "abcd".repeat(16),
      },
    ],
    unchanged: [],
  },
  gaps_closed: [
    {
      cluster_id: "old1",
      representative: "old gap closed",
      count: 5,
      n_users: 2,
      skill_name: null,
      covered: false,
      reason: "unmatched",
    },
  ],
  gaps_new: [],
  candidates_advancing: [
    {
      candidate_id: "fobo:s:a",
      rung: "skill",
      title: "why recon break",
      from_status: "accumulating",
      to_status: "ready",
      change: "advanced",
    },
  ],
};

const skillsBody = [
  {
    filename: "fobo-break-triage.md",
    bytes: 100,
    valid: true,
    name: "fobo-break-triage",
    description: "triage",
    n_example_prompts: 2,
  },
];

const runsBody = [
  {
    capability_id: "fobo",
    run_id: RUN_ID,
    window_start: "2026-09-01T00:00:00+00:00",
    window_end: "2026-09-08T00:00:00+00:00",
    n_spans: 100,
    n_in_scope_spans: 40,
    n_clusters: 3,
    n_rung1_candidates: 1,
    n_rung2_candidates: 0,
    status: "ok",
    analytics_ready: true,
  },
  {
    capability_id: "fobo",
    run_id: PREV_RUN,
    window_start: "2026-08-31T00:00:00+00:00",
    window_end: "2026-09-07T00:00:00+00:00",
    n_spans: 80,
    n_in_scope_spans: 30,
    n_clusters: 2,
    n_rung1_candidates: 0,
    n_rung2_candidates: 0,
    status: "ok",
    analytics_ready: true,
  },
  {
    capability_id: "fobo",
    run_id: OLDER_RUN,
    window_start: "2026-08-25T00:00:00+00:00",
    window_end: "2026-09-01T00:00:00+00:00",
    n_spans: 50,
    n_in_scope_spans: 20,
    n_clusters: 1,
    n_rung1_candidates: 0,
    n_rung2_candidates: 0,
    status: "partial",
    analytics_ready: true,
  },
];

function mock(opts?: { jobState?: string }) {
  const jobState = opts?.jobState ?? "done";
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const u = new URL(String(url), "http://x");
    const p = decodeURIComponent(u.pathname);
    if (p === "/capabilities/fobo") return json(capBody);
    if (p === "/capabilities/fobo/skills") return json(skillsBody);
    if (p === "/capabilities/fobo/runs") return json(runsBody);
    if (p === "/capabilities/fobo/candidates") return json(resultsBody.rung1_candidates);
    if (p === `/capabilities/fobo/runs/${OLDER_RUN}/results`) return json(olderResultsBody);
    if (p.endsWith("/results") && p.includes("/runs/")) return json(resultsBody);
    if (p === "/capabilities/fobo/runs/compare") return json(compareBody);
    if (p === "/capabilities/fobo/jobs" && init?.method === "POST")
      return json({
        job_id: "job-1",
        state: "queued",
        stage: "queued",
        progress: 0,
        message: null,
      });
    if (p === "/capabilities/fobo/jobs/job-1") {
      if (jobState === "running") {
        return json({
          state: "running",
          stage: "scraping",
          progress: 0.35,
          message: "Pulling spans…",
          run_id: null,
          error: null,
        });
      }
      return json({
        state: "done",
        stage: "done",
        progress: 1,
        message: "Complete",
        run_id: RUN_ID,
        error: null,
      });
    }
    if (p === "/capabilities/preview" && init?.method === "POST")
      return json({
        n_spans: 10,
        n_llm_spans: 8,
        n_users: 2,
        n_sessions: 3,
        n_spans_in_store: 100,
        window_days: 7,
        distinct: { workflow_stage: [], asset_class: [], project: [] },
        sample_prompts: [],
      });
    return new Response(JSON.stringify({ detail: `no mock for ${p}` }), {
      status: 404,
      headers: { "content-type": "application/json" },
    });
  });
}

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

test("lands on Results for the last run with skill gaps first", async () => {
  mock();
  renderWithProviders(<CapabilityDetail />, { route: "/c/fobo", path: "/c/:id" });
  await waitFor(() => expect(screen.getByTestId("run-results")).toBeInTheDocument());

  // Single dense chrome panel — no stacked outcome subtitle.
  const chrome = screen.getByTestId("capability-chrome");
  expect(screen.queryByTestId("outcome-framing")).not.toBeInTheDocument();
  expect(screen.queryByText(/Gaps first/i)).not.toBeInTheDocument();
  expect(within(chrome).getByRole("heading", { level: 1, name: /^FOBO$/i })).toBeInTheDocument();
  expect(within(chrome).getByTestId("capability-status-badge")).toHaveTextContent(/active/i);
  expect(within(chrome).getByTestId("capability-filter-line")).toHaveTextContent(
    /project=pnl-agent/,
  );
  expect(within(chrome).getByTestId("capability-filter-line")).toHaveTextContent(
    /workflow_stage=fobo_recon/,
  );
  expect(within(chrome).getByRole("link", { name: /^Capabilities$/i })).toBeInTheDocument();
  // Version chrome lives in the combined capability header, not duplicated under results.
  expect(within(chrome).getByTestId("results-chrome")).toBeInTheDocument();
  expect(
    within(screen.getByTestId("run-results")).queryByTestId("results-chrome"),
  ).not.toBeInTheDocument();
  expect(within(chrome).getByTestId("version-strip")).toBeInTheDocument();
  expect(within(chrome).getByTestId("funnel-strip")).toBeInTheDocument();
  expect(within(chrome).getByRole("navigation", { name: /Run workflow/i })).toBeInTheDocument();
  expect(screen.queryByText(/Window & skills/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/Gaps & decisions/i)).not.toBeInTheDocument();

  const funnel = within(chrome).getByTestId("funnel-strip");
  expect(funnel).toHaveTextContent(/40/);
  expect(funnel).toHaveTextContent(/in-scope/i);
  expect(funnel).toHaveTextContent(/gaps/i);
  expect(funnel).toHaveTextContent(/ready to decide/i);
  expect(funnel).not.toHaveTextContent(/unmatched/i);
  await userEvent.click(within(chrome).getByTestId("funnel-more"));
  expect(funnel).toHaveTextContent(/unmatched/i);

  expect(screen.getByRole("heading", { name: /^Skill gaps$/i })).toBeInTheDocument();
  expect(screen.getAllByText(/why is recon break unmatched/i).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/Promote to skill/i).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/Make deterministic/i).length).toBeGreaterThan(0);
  expect(screen.getAllByText("why recon break").length).toBeGreaterThan(0);
  expect(screen.getByText(/TRUNCATED/)).toBeInTheDocument();
  await waitFor(() =>
    expect(
      within(screen.getByTestId("promotion-queue")).getByTestId(
        "promotion-card-decide",
      ),
    ).toBeInTheDocument(),
  );
  const queue = screen.getByTestId("promotion-queue");
  expect(
    within(queue).getByRole("heading", { name: "Decide" }),
  ).toBeInTheDocument();
  expect(
    within(queue).getByRole("heading", { name: "Write file" }),
  ).toBeInTheDocument();
  expect(
    within(queue).getByRole("heading", { name: "Done" }),
  ).toBeInTheDocument();
  expect(within(queue).getByTestId("promotion-card-write")).toHaveTextContent(
    "Nothing here",
  );
  expect(within(queue).getByTestId("promotion-card-done")).toHaveTextContent(
    "Nothing here",
  );
  expect(within(chrome).getByTestId("latest-run-badge")).toBeInTheDocument();
  expect(within(chrome).getByRole("button", { name: /Run next version/i })).toBeInTheDocument();
  // History lives only in the wizard step strip — not duplicated in chrome actions or body.
  expect(
    within(screen.getByTestId("results-chrome")).queryByRole("button", {
      name: /^History$/i,
    }),
  ).not.toBeInTheDocument();
  expect(
    within(screen.getByTestId("run-results")).queryByRole("button", {
      name: /^History$/i,
    }),
  ).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("navigation", { name: /Run workflow/i })).getByRole(
      "button",
      { name: /^History$/i },
    ),
  ).toBeInTheDocument();
  expect(screen.getByTestId("usage-button")).toHaveAttribute(
    "href",
    "/c/fobo/analytics",
  );
  // Idle Running is a non-interactive milestone, not a nav button.
  const runningStep = screen.getByTestId("wizard-running-step");
  expect(runningStep.tagName).toBe("SPAN");
  expect(runningStep).toHaveAttribute(
    "title",
    "Shown while a run is in progress",
  );
  expect(
    within(screen.getByRole("navigation", { name: /Run workflow/i })).queryByRole(
      "button",
      { name: /^Running$/i },
    ),
  ).not.toBeInTheDocument();
  expect(
    within(screen.getByTestId("run-results")).queryByRole("button", {
      name: /Browse history/i,
    }),
  ).not.toBeInTheDocument();
});

test("shows version comparison against the previous run", async () => {
  mock();
  renderWithProviders(<CapabilityDetail />, { route: "/c/fobo", path: "/c/:id" });
  await waitFor(() =>
    expect(screen.getByText(/fobo-break-triage.md updated/i)).toBeInTheDocument(),
  );
  expect(screen.getAllByText(/Since last version/i).length).toBeGreaterThan(0);
  expect(screen.getByText(/old gap closed/i)).toBeInTheDocument();
  expect(screen.getByText(/accumulating → ready/i)).toBeInTheDocument();
  expect(screen.getByTestId("compare-picker")).toBeInTheDocument();
});

test("History step lists runs by day; clicking opens that version's Results", async () => {
  mock();
  renderWithProviders(<CapabilityDetail />, { route: "/c/fobo", path: "/c/:id" });
  await waitFor(() => screen.getByTestId("run-results"));

  const nav = screen.getByRole("navigation", { name: /Run workflow/i });
  await userEvent.click(within(nav).getByRole("button", { name: /^History$/i }));
  await waitFor(() => expect(screen.getByTestId("run-history")).toBeInTheDocument());
  expect(screen.getByText(/Version history/i)).toBeInTheDocument();
  expect(screen.getByText(/Same-day versions don't block each other/i)).toBeInTheDocument();
  expect(screen.getByTestId("history-latest-badge")).toBeInTheDocument();
  expect(screen.getByTestId(`history-run-${OLDER_RUN}`)).toBeInTheDocument();

  await userEvent.click(screen.getByTestId(`history-run-${OLDER_RUN}`));
  await waitFor(() => expect(screen.getByTestId("run-results")).toBeInTheDocument());
  expect(screen.getByText(/older uncovered ask/i)).toBeInTheDocument();
  expect(screen.getByTestId("older-run-badge")).toBeInTheDocument();
  expect(screen.getByTestId("older-run-note")).toHaveTextContent(/older snapshot/i);
  expect(screen.getByTestId("run-status-badge")).toHaveTextContent(/partial/i);
  expect(screen.getByTestId("run-status-badge").getAttribute("title")).toMatch(
    /truncat|incomplete/i,
  );
});

test("Run next version returns to Setup with required from/to", async () => {
  mock();
  renderWithProviders(<CapabilityDetail />, { route: "/c/fobo", path: "/c/:id" });
  await waitFor(() => screen.getByRole("button", { name: /Run next version/i }));
  await userEvent.click(screen.getByRole("button", { name: /Run next version/i }));
  await waitFor(() => expect(screen.getByTestId("run-setup")).toBeInTheDocument());
  expect(screen.getByTestId("setup-howto")).toHaveTextContent(/Window \+ skills/i);
  expect(screen.getByTestId("setup-card")).toBeInTheDocument();
  expect(screen.getByLabelText(/window start date/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/window end date/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Run now$/i })).toBeInTheDocument();
  expect(screen.getByText(/span filter & preview/i)).toBeInTheDocument();
  // Visual order: Window → Skills → Run (no numbered 1/2/3 chaos)
  expect(screen.queryByText(/1\.\s*Pick window/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/3\.\s*Run now/i)).not.toBeInTheDocument();
});

test("Run now enqueues a closed from/to job and shows Running", async () => {
  const spy = mock({ jobState: "running" });
  renderWithProviders(<CapabilityDetail />, { route: "/c/fobo", path: "/c/:id" });
  await waitFor(() => screen.getByRole("button", { name: /Run next version/i }));
  await userEvent.click(screen.getByRole("button", { name: /Run next version/i }));
  await waitFor(() => screen.getByRole("button", { name: /run now/i }));

  await userEvent.clear(screen.getByLabelText(/window start date/i));
  await userEvent.type(screen.getByLabelText(/window start date/i), "2026-05-01");
  await userEvent.clear(screen.getByLabelText(/window end date/i));
  await userEvent.type(screen.getByLabelText(/window end date/i), "2026-06-01");
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
  const post = spy.mock.calls.find(
    ([u, i]) =>
      String(u).endsWith("/capabilities/fobo/jobs") &&
      (i as RequestInit).method === "POST",
  );
  const body = JSON.parse((post![1] as RequestInit).body as string);
  expect(body.from).toBe("2026-05-01T00:00:00.000Z");
  expect(body.to).toBe("2026-06-01T23:59:59.999Z");

  await waitFor(() => expect(screen.getByTestId("run-progress")).toBeInTheDocument());
  expect(screen.getByText(/Pulling spans/i)).toBeInTheDocument();
  expect(screen.queryByTestId("lane-board")).not.toBeInTheDocument();
});
