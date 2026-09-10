import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { CandidateDetail } from "./CandidateDetail";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const detail = {
  candidate: {
    candidate_id: "fobo:s:a",
    capability_id: "fobo",
    rung: "skill",
    subtype: "new_skill",
    status: "ready",
    title: "why recon break",
    matched_skill: null,
    current_evidence: { count: 40, n_users: 6 },
    cluster_id: "a",
    promoted_artifact_paths: [],
  },
  observations: [
    { run_id: "2026-09-07T10:00:00+00:00", count: 20, score: 0.8, met_evidence_bar: 0, signals: {} },
    { run_id: "2026-09-08T10:00:00+00:00", count: 40, score: 1.0, met_evidence_bar: 1, signals: {} },
  ],
  decisions: [],
};

function mock(detailOverride: typeof detail = detail) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const p = new URL(String(url), "http://x").pathname;
    if (p.endsWith("/decision") && init?.method === "POST")
      return new Response("{}", { status: 200 });
    if (p.endsWith("/promote") && init?.method === "POST")
      return new Response(
        JSON.stringify({
          paths: ["capabilities/fobo/skills/why-recon-break.md"],
          contents: [],
          wrote_files: true,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    if (p.endsWith("/artifact/preview"))
      return new Response(
        JSON.stringify({
          contents: [{ path: "capabilities/fobo/skills/why-recon-break.md", body: "# draft" }],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    if (p.startsWith("/candidates/"))
      return new Response(JSON.stringify(detailOverride), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    if (p.startsWith("/capabilities/"))
      return new Response(
        JSON.stringify({
          capability: { id: "fobo", name: "FOBO", thresholds: {} },
          summary: { id: "fobo" },
          skill_files: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    return new Response("null", { status: 404 });
  });
}

test("shows the trend and lets a reviewer reject", async () => {
  const spy = mock();
  renderWithProviders(<CandidateDetail />, {
    route: "/c/fobo/candidate/fobo:s:a",
    path: "/c/:id/candidate/:cid",
  });
  await waitFor(() => expect(screen.getByText(/why recon break/)).toBeInTheDocument());
  expect(screen.getByRole("img", { name: "trend" })).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /^reject$/i }));
  await userEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
  await waitFor(() =>
    expect(
      spy.mock.calls.some(
        ([u, i]) =>
          String(u).endsWith("/decision") && (i as RequestInit).method === "POST",
      ),
    ).toBe(true),
  );
});

test("accept is disabled unless status is ready — reopen is disabled here", async () => {
  mock();
  renderWithProviders(<CandidateDetail />, {
    route: "/c/fobo/candidate/fobo:s:a",
    path: "/c/:id/candidate/:cid",
  });
  await waitFor(() => screen.getByRole("button", { name: /^accept$/i }));
  expect(screen.getByRole("button", { name: /^accept$/i })).toBeEnabled(); // ready
  expect(screen.getByRole("button", { name: /^reopen$/i })).toBeDisabled();
});

test("accept shows why it is disabled when status is new", async () => {
  const notReady = {
    ...detail,
    candidate: { ...detail.candidate, status: "new" },
    observations: [detail.observations[1]],
  };
  mock(notReady);
  renderWithProviders(<CandidateDetail />, {
    route: "/c/fobo/candidate/fobo:s:a",
    path: "/c/:id/candidate/:cid",
  });
  const accept = await screen.findByRole("button", { name: /^accept$/i });
  expect(accept).toBeDisabled();
  expect(accept).toHaveAttribute("title", expect.stringMatching(/status ready/i));
  expect(screen.getByText(/Evidence bar met on latest run/i)).toBeInTheDocument();
});

test("accept cites count vs required when latest run misses the bar", async () => {
  const accumulating = {
    ...detail,
    candidate: { ...detail.candidate, status: "accumulating" },
    observations: [
      {
        run_id: "2026-09-10T15:28:00+00:00",
        count: 15,
        n_users: 7,
        score: 1.0,
        met_evidence_bar: 1,
        signals: {},
      },
      {
        run_id: "2026-09-10T19:00:00+00:00",
        count: 6,
        n_users: 4,
        score: 1.0,
        met_evidence_bar: 0,
        signals: {},
      },
    ],
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const p = new URL(String(url), "http://x").pathname;
    if (p.startsWith("/candidates/"))
      return new Response(JSON.stringify(accumulating), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    if (p.startsWith("/capabilities/"))
      return new Response(
        JSON.stringify({
          capability: {
            id: "fobo",
            name: "FOBO",
            thresholds: { rung1_min_count: 15, rung1_min_users: 3 },
          },
          summary: { id: "fobo" },
          skill_files: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    return new Response("null", { status: 404 });
  });
  renderWithProviders(<CandidateDetail />, {
    route: "/c/fobo/candidate/fobo:s:a",
    path: "/c/:id/candidate/:cid",
  });
  const accept = await screen.findByRole("button", { name: /^accept$/i });
  expect(accept).toBeDisabled();
  expect(
    screen.getByText(/Latest run count 6 < required 15/i),
  ).toBeInTheDocument();
});

test("ready status shows guided steps and blocks write until accept", async () => {
  mock();
  renderWithProviders(<CandidateDetail />, {
    route: "/c/fobo/candidate/fobo:s:a",
    path: "/c/:id/candidate/:cid",
  });
  await screen.findByText(/why recon break/);
  expect(screen.getByLabelText("Candidate workflow")).toBeInTheDocument();
  expect(screen.getByText(/Step 1 Decide/i)).toBeInTheDocument();
  expect(screen.getByText(/Step 2 Write file/i)).toBeInTheDocument();
  expect(screen.getByText(/First accept, then you can write the file/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /write skill file/i })).toBeDisabled();
  expect(screen.getByRole("button", { name: /preview files first/i })).toBeEnabled();
  expect(screen.queryByRole("button", { name: /^promote$/i })).not.toBeInTheDocument();
});

test("accepted status enables write skill file and shows promote panel copy", async () => {
  const accepted = {
    ...detail,
    candidate: { ...detail.candidate, status: "accepted" },
  };
  mock(accepted);
  renderWithProviders(<CandidateDetail />, {
    route: "/c/fobo/candidate/fobo:s:a",
    path: "/c/:id/candidate/:cid",
  });
  await screen.findByRole("heading", { name: /Write skill draft into FOBO/i });
  expect(
    screen.getByText(/Creates\/updates a markdown skill file under/i),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /write skill file/i })).toBeEnabled();
  expect(screen.getByText(/Step 2 Write file/i).closest("[aria-current]")).toHaveAttribute(
    "aria-current",
    "step",
  );
});

test("writing the skill file shows paths and next-step links", async () => {
  const accepted = {
    ...detail,
    candidate: { ...detail.candidate, status: "accepted" },
  };
  const spy = mock(accepted);
  renderWithProviders(<CandidateDetail />, {
    route: "/c/fobo/candidate/fobo:s:a",
    path: "/c/:id/candidate/:cid",
  });
  await screen.findByRole("button", { name: /write skill file/i });
  await userEvent.click(screen.getByRole("button", { name: /write skill file/i }));
  await waitFor(() =>
    expect(
      spy.mock.calls.some(
        ([u, i]) =>
          String(u).includes("/promote") && (i as RequestInit).method === "POST",
      ),
    ).toBe(true),
  );
  expect(await screen.findByText(/Skill draft written/i)).toBeInTheDocument();
  expect(
    screen.getByText("capabilities/fobo/skills/why-recon-break.md"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Edit the file, then Run next version/i),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /^Back to Results$/i })).toHaveAttribute(
    "href",
    "/c/fobo?step=results",
  );
  expect(screen.getByRole("link", { name: /^Setup skills$/i })).toHaveAttribute(
    "href",
    "/c/fobo?step=setup",
  );
});

test("promoted status restores written paths from the candidate", async () => {
  const promoted = {
    ...detail,
    candidate: {
      ...detail.candidate,
      status: "promoted",
      promoted_artifact_paths: ["capabilities/fobo/skills/why-recon-break.md"],
    },
  };
  mock(promoted);
  renderWithProviders(<CandidateDetail />, {
    route: "/c/fobo/candidate/fobo:s:a",
    path: "/c/:id/candidate/:cid",
  });
  expect(await screen.findByText(/Skill draft written/i)).toBeInTheDocument();
  expect(
    screen.getByText("capabilities/fobo/skills/why-recon-break.md"),
  ).toBeInTheDocument();
  expect(screen.getByText(/Step 3 Review folder/i).closest("[aria-current]")).toHaveAttribute(
    "aria-current",
    "step",
  );
});
