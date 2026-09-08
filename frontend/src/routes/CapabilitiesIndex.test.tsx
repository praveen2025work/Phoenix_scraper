import { screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { CapabilitiesIndex } from "./CapabilitiesIndex";
import { mockFetch, renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

test("lists capability cards with last-run + candidate badges", async () => {
  mockFetch({
    "/capabilities": [
      {
        id: "fobo",
        name: "FOBO",
        status: "active",
        filter: { workflow_stage: "fobo_recon" },
        window_days: 30,
        last_run: { run_id: "2026-09-08T10:00:00+00:00", status: "ok" },
        candidates: { skill: { ready: 2, accumulating: 1 }, deterministic: { ready: 1 } },
      },
    ],
  });
  renderWithProviders(<CapabilitiesIndex />);
  await waitFor(() => expect(screen.getByText("FOBO")).toBeInTheDocument());
  expect(screen.getByText(/stage=fobo_recon/)).toBeInTheDocument();
  expect(screen.getByText(/Rung 1: 2 ready/)).toBeInTheDocument();
  expect(screen.getByText(/Rung 2: 1 ready/)).toBeInTheDocument();
});

test("empty state when there are no capabilities", async () => {
  mockFetch({ "/capabilities": [] });
  renderWithProviders(<CapabilitiesIndex />);
  await waitFor(() =>
    expect(screen.getByText(/create one to start/i)).toBeInTheDocument(),
  );
});
