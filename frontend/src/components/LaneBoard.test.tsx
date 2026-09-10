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

test("groups candidates into status lanes", () => {
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
  expect(screen.getByRole("heading", { name: /Ready · 1/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Building evidence · 1/i })).toBeInTheDocument();
  expect(screen.getByText("why recon break")).toBeInTheDocument();
  expect(screen.getByText("ready")).toHaveAttribute("data-status", "ready");
  expect(screen.getByText("accumulating")).toHaveAttribute("data-status", "accumulating");
  expect(screen.getAllByText("Review evidence").length).toBe(2);
  expect(screen.getAllByText("40 asks · 6 users").length).toBe(2);
  expect(screen.queryByText(/Ready — open to accept/i)).not.toBeInTheDocument();
});

test("hides promoted behind a toggle by default", async () => {
  renderWithProviders(
    <LaneBoard
      capabilityId="fobo"
      candidates={[{ ...base, status: "promoted", title: "already shipped" }]}
    />,
    { route: "/c/fobo", path: "/c/:id" },
  );
  expect(screen.queryByText("already shipped")).not.toBeInTheDocument();
  expect(
    screen.getByText(/No active candidates — expand promoted or hidden below/i),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /show promoted \(1\)/i }));
  expect(screen.getByText("already shipped")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Promoted · 1/i })).toBeInTheDocument();
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
