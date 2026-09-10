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
  expect(screen.getByText(/Promote to skill:/i)).toBeInTheDocument();
  expect(screen.getByText(/Make deterministic:/i)).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
  expect(screen.getByText("1")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Open & review gaps/i })).toHaveAttribute(
    "href",
    "/c/fobo",
  );
  expect(screen.getByTestId("home-outcome")).toHaveTextContent(/Choose a capability/i);
  expect(screen.getByText(/Your capabilities/i)).toBeInTheDocument();
});

test("empty state when there are no capabilities", async () => {
  mockFetch({ "/capabilities": [] });
  renderWithProviders(<CapabilitiesIndex />);
  await waitFor(() =>
    expect(screen.getByText(/create one to start/i)).toBeInTheDocument(),
  );
});
