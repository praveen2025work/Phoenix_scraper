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
  },
  observations: [
    { run_id: "2026-09-07T10:00:00+00:00", count: 20, score: 0.8, met_evidence_bar: 0, signals: {} },
    { run_id: "2026-09-08T10:00:00+00:00", count: 40, score: 1.0, met_evidence_bar: 1, signals: {} },
  ],
  decisions: [],
};

function mock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const p = new URL(String(url), "http://x").pathname;
    if (p.endsWith("/decision") && init?.method === "POST")
      return new Response("{}", { status: 200 });
    if (p.startsWith("/candidates/"))
      return new Response(JSON.stringify(detail), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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
