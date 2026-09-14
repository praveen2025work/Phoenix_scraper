import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { RunResults, RunResultsChrome } from "./RunResults";
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
  expect(btn).toHaveAttribute(
    "href",
    `/c/fobo/analytics?run=${encodeURIComponent(RUN_ID)}`,
  );
});

test("Usage is an enabled outline button linking to analytics when ready", async () => {
  mockApis({ analyticsReady: true });
  renderWithProviders(
    <RunResultsChrome capabilityId="fobo" runId={RUN_ID} onRunNext={() => {}} />,
  );
  const btn = await screen.findByTestId("usage-button");
  await waitFor(() => expect(btn).not.toBeDisabled());
  expect(btn).toHaveAttribute(
    "href",
    `/c/fobo/analytics?run=${encodeURIComponent(RUN_ID)}`,
  );
  expect(btn).toHaveTextContent(/^Usage$/);
});

test("suggested skill updates show old vs proposed with copy and download", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = new URL(String(url), "http://x");
    if (u.pathname.endsWith("/results")) {
      return json({
        ...resultsBody,
        analytics_ready: true,
        suggested_skill_updates: [
          {
            skill_name: "fx-recon-triage",
            source_file: "fx-recon-triage.md",
            uncovered_asks: 4,
            n_users: 2,
            n_new_prompts: 1,
            new_prompts: ["Which tickets sit unconfirmed?"],
            new_keywords: ["unconfirmed"],
            upload_filename: "fx-recon-triage.md",
            current_content: "---\nname: fx-recon-triage\n---\n",
            proposed_content:
              "---\nname: fx-recon-triage\nexample_prompts:\n  - Which tickets sit unconfirmed?\n---\n",
          },
        ],
      });
    }
    if (u.pathname === "/capabilities/fobo/runs") return json([{ run_id: RUN_ID }]);
    if (u.pathname === "/capabilities/fobo/candidates") return json([]);
    return json([]);
  });

  renderWithProviders(
    <RunResults capabilityId="fobo" runId={RUN_ID} onRunNext={() => {}} />,
  );

  expect(await screen.findByTestId("suggested-skill-update")).toBeInTheDocument();
  expect(screen.getByTestId("skill-content-diff")).toBeInTheDocument();
  expect(screen.getByLabelText(/current uploaded/i)).toHaveTextContent(
    "name: fx-recon-triage",
  );
  expect(screen.getByLabelText(/proposed/i)).toHaveTextContent(
    "Which tickets sit unconfirmed?",
  );
  expect(
    screen.getByRole("button", { name: /copy proposed/i }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /download fx-recon-triage\.md/i }),
  ).toBeInTheDocument();
});
