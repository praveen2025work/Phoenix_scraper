import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { Candidate } from "@/api/hooks";
import { LaneBoard } from "./LaneBoard";
import { renderWithProviders } from "@/test/renderWithProviders";

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

test("groups candidates into status columns", () => {
  renderWithProviders(
    <LaneBoard
      capabilityId="fobo"
      candidates={[
        base,
        { ...base, candidate_id: "fobo:s:b", status: "accumulating", title: "explain break" },
      ]}
    />,
    { route: "/c/fobo", path: "/c/:id" },
  );
  expect(screen.getByRole("heading", { name: /ready \(1\)/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /accumulating \(1\)/i })).toBeInTheDocument();
  expect(screen.getByText("why recon break")).toBeInTheDocument();
});

test("hides rejected/snoozed/stale behind a toggle", async () => {
  renderWithProviders(
    <LaneBoard capabilityId="fobo" candidates={[{ ...base, status: "rejected" }]} />,
    { route: "/c/fobo", path: "/c/:id" },
  );
  expect(screen.queryByText("why recon break")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /show rejected/i }));
  expect(screen.getByText("why recon break")).toBeInTheDocument();
});
