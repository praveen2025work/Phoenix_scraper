import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Candidate } from "@/api/hooks";
import {
  acceptedSkillCandidates,
  PromotionQueue,
  segregateByLane,
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
      {
        ...base,
        candidate_id: "a3",
        status: "accepted",
        rung: "skill",
        title: "{'query': 'select:mcp__data-analysis__query_data'}",
      },
    ]).map((c) => c.candidate_id),
  ).toEqual(["a1"]);
});

test("segregateByLane rehomes MCP payloads out of skill", () => {
  const lanes = segregateByLane([
    base,
    {
      ...base,
      candidate_id: "fobo:s:mcp",
      title: "{'query': 'select:mcp__database__list_tables'}",
    },
    {
      ...base,
      candidate_id: "fobo:d:1",
      rung: "deterministic",
      title: "SELECT * FROM breaks WHERE session_id = 'x'",
    },
  ]);
  expect(lanes.skill.map((c) => c.candidate_id)).toEqual(["fobo:s:a"]);
  expect(lanes.deterministic.map((c) => c.candidate_id)).toEqual([
    "fobo:s:mcp",
    "fobo:d:1",
  ]);
});

test("renders segregated skill and deterministic lanes", async () => {
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
    {
      ...base,
      candidate_id: "fobo:s:mcp",
      status: "ready",
      title: "{'query': 'select:mcp__data-analysis__query_data'}",
    },
  ]);
  renderWithProviders(<PromotionQueue capabilityId="fobo" />, {
    route: "/c/fobo",
    path: "/c/:id",
  });

  await waitFor(() =>
    expect(screen.getByTestId("promotion-queue")).toHaveTextContent(
      /Skill questions and deterministic payloads stay in separate lanes/i,
    ),
  );

  const skillDecide = screen.getByTestId("promotion-card-skill-decide");
  const detDecide = screen.getByTestId("promotion-card-deterministic-decide");

  expect(within(skillDecide).getByText("why recon break")).toBeInTheDocument();
  expect(within(skillDecide).queryByText(/mcp__/i)).not.toBeInTheDocument();
  expect(within(detDecide).getByText(/mcp__/i)).toBeInTheDocument();

  expect(screen.getByTestId("promotion-lane-skill")).toBeInTheDocument();
  expect(screen.getByTestId("promotion-lane-deterministic")).toBeInTheDocument();

  const write = screen.getByTestId("promotion-card-skill-write");
  const done = screen.getByTestId("promotion-card-skill-done");
  expect(within(write).getByText("accepted gap")).toBeInTheDocument();
  expect(within(done).getByText("done gap")).toBeInTheDocument();
});

test("empty sections show Nothing here", async () => {
  mockCandidates([base]);
  renderWithProviders(<PromotionQueue capabilityId="fobo" />, {
    route: "/c/fobo",
    path: "/c/:id",
  });

  await screen.findByText("why recon break");

  expect(
    within(screen.getByTestId("promotion-card-skill-write")).getByRole("status"),
  ).toHaveTextContent("Nothing here");
  expect(
    within(screen.getByTestId("promotion-card-skill-done")).getByRole("status"),
  ).toHaveTextContent("Nothing here");
  expect(
    within(screen.getByTestId("promotion-card-skill-decide")).queryByRole("status"),
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
    expect(screen.getByTestId("promotion-card-skill-done")).toHaveTextContent(
      "done gap",
    ),
  );
  expect(
    within(screen.getByTestId("promotion-card-skill-done")).getByText("View"),
  ).toBeInTheDocument();
});
