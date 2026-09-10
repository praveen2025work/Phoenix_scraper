import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { RunHistory } from "./RunHistory";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const runs = [
  {
    capability_id: "fobo",
    run_id: "2026-09-08T10:00:00+00:00",
    window_start: "2026-09-01T00:00:00+00:00",
    window_end: "2026-09-08T00:00:00+00:00",
    n_clusters: 3,
    n_rung1_candidates: 1,
    n_rung2_candidates: 0,
    status: "ok",
  },
  {
    capability_id: "fobo",
    run_id: "2026-09-08T08:00:00+00:00",
    window_start: "2026-09-01T00:00:00+00:00",
    window_end: "2026-09-08T00:00:00+00:00",
    n_clusters: 2,
    n_rung1_candidates: 0,
    n_rung2_candidates: 0,
    status: "ok",
  },
  {
    capability_id: "fobo",
    run_id: "2026-09-01T10:00:00+00:00",
    window_start: "2026-08-25T00:00:00+00:00",
    window_end: "2026-09-01T00:00:00+00:00",
    n_clusters: 1,
    n_rung1_candidates: 0,
    n_rung2_candidates: 1,
    status: "partial",
  },
];

test("groups runs by day with week labels and selects a run", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(runs), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  const onSelect = vi.fn();
  renderWithProviders(
    <RunHistory capabilityId="fobo" onSelectRun={onSelect} />,
  );
  await waitFor(() => expect(screen.getByTestId("run-history")).toBeInTheDocument());
  expect(screen.getAllByText(/Week of/i).length).toBeGreaterThan(0);
  expect(screen.getByTestId("history-run-2026-09-08T10:00:00+00:00")).toBeInTheDocument();
  expect(screen.getByTestId("history-run-2026-09-01T10:00:00+00:00")).toBeInTheDocument();
  expect(screen.getByTestId("history-latest-badge")).toBeInTheDocument();
  expect(screen.getByText(/Same-day versions don't block each other/i)).toBeInTheDocument();

  await userEvent.click(screen.getByTestId("history-run-2026-09-01T10:00:00+00:00"));
  expect(onSelect).toHaveBeenCalledWith("2026-09-01T10:00:00+00:00");
});

test("empty history offers setup path", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  const onNew = vi.fn();
  renderWithProviders(
    <RunHistory capabilityId="fobo" onSelectRun={() => {}} onNewRun={onNew} />,
  );
  await waitFor(() => expect(screen.getByText(/No versions yet/i)).toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: /Go to Setup/i }));
  expect(onNew).toHaveBeenCalled();
});
