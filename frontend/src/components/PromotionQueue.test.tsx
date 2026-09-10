import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Candidate } from "@/api/hooks";
import {
  acceptedSkillCandidates,
  PromotionQueue,
} from "./PromotionQueue";
import { mockFetch, renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const base: Candidate = {
  candidate_id: "fobo:s:a",
  capability_id: "fobo",
  rung: "skill",
  subtype: "new_skill",
  status: "ready",
  title: "why recon break",
  matched_skill: null,
  current_evidence: { count: 40, n_users: 6 },
  cluster_id: "a",
};

function mockCandidates(items: Candidate[]) {
  mockFetch({ "/capabilities/fobo/candidates": items });
}

test("acceptedSkillCandidates keeps accepted skill rung only", () => {
  expect(
    acceptedSkillCandidates([
      base,
      { ...base, candidate_id: "a1", status: "accepted", rung: "skill" },
      {
        ...base,
        candidate_id: "a2",
        status: "accepted",
        rung: "deterministic",
      },
    ]).map((c) => c.candidate_id),
  ).toEqual(["a1"]);
});

test("renders three section cards with counts and intro", async () => {
  mockCandidates([
    base,
    {
      ...base,
      candidate_id: "fobo:s:b",
      status: "accepted",
      title: "accepted gap",
    },
    {
      ...base,
      candidate_id: "fobo:s:c",
      status: "promoted",
      title: "done gap",
    },
  ]);
  renderWithProviders(<PromotionQueue capabilityId="fobo" />, {
    route: "/c/fobo",
    path: "/c/:id",
  });

  await waitFor(() =>
    expect(screen.getByTestId("promotion-queue")).toHaveTextContent(
      /Finish these in order: decide → write the skill file/i,
    ),
  );

  const decide = screen.getByTestId("promotion-card-decide");
  const write = screen.getByTestId("promotion-card-write");
  const done = screen.getByTestId("promotion-card-done");

  expect(within(decide).getByRole("heading", { name: "Decide" })).toBeInTheDocument();
  expect(within(decide).getByText("why recon break")).toBeInTheDocument();
  expect(
    within(decide).getByRole("link", { name: /why recon break.*Decide/i }),
  ).toBeInTheDocument();

  expect(within(write).getByRole("heading", { name: "Write file" })).toBeInTheDocument();
  expect(within(write).getByText("accepted gap")).toBeInTheDocument();
  expect(
    within(write).getByRole("link", { name: /accepted gap.*Write file/i }),
  ).toBeInTheDocument();

  expect(within(done).getByRole("heading", { name: "Done" })).toBeInTheDocument();
  expect(within(done).getByText("done gap")).toBeInTheDocument();
  expect(
    within(done).getByRole("link", { name: /done gap.*View/i }),
  ).toBeInTheDocument();

  // All three visible at once (not tab-hidden)
  expect(screen.getByText("why recon break")).toBeInTheDocument();
  expect(screen.getByText("accepted gap")).toBeInTheDocument();
  expect(screen.getByText("done gap")).toBeInTheDocument();

  // DOM order: Decide → Write file → Done
  const cards = screen.getAllByTestId(/promotion-card-/);
  expect(cards.map((el) => el.getAttribute("data-testid"))).toEqual([
    "promotion-card-decide",
    "promotion-card-write",
    "promotion-card-done",
  ]);
});

test("empty sections show Nothing here", async () => {
  mockCandidates([base]);
  renderWithProviders(<PromotionQueue capabilityId="fobo" />, {
    route: "/c/fobo",
    path: "/c/:id",
  });

  await screen.findByText("why recon break");

  expect(
    within(screen.getByTestId("promotion-card-write")).getByRole("status"),
  ).toHaveTextContent("Nothing here");
  expect(
    within(screen.getByTestId("promotion-card-done")).getByRole("status"),
  ).toHaveTextContent("Nothing here");
  expect(
    within(screen.getByTestId("promotion-card-decide")).queryByRole("status"),
  ).not.toBeInTheDocument();
});

test("Done card uses View CTA", async () => {
  mockCandidates([
    {
      ...base,
      candidate_id: "fobo:s:c",
      status: "promoted",
      title: "done gap",
    },
  ]);
  renderWithProviders(<PromotionQueue capabilityId="fobo" />, {
    route: "/c/fobo",
    path: "/c/:id",
  });

  await waitFor(() =>
    expect(screen.getByTestId("promotion-card-done")).toHaveTextContent(
      "done gap",
    ),
  );
  expect(
    within(screen.getByTestId("promotion-card-done")).getByText("View"),
  ).toBeInTheDocument();
});
