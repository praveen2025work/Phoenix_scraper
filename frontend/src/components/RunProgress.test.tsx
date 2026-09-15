import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JobDto } from "@/api/hooks";
import { RunProgress } from "./RunProgress";

function job(over: Partial<JobDto> = {}): JobDto {
  return {
    job_id: "j1",
    state: "running",
    stage: "analyzing",
    progress: 0.5,
    message: "Clustered 12 user-ask patterns",
    run_id: null,
    error: null,
    stats: {
      n_in_scope: 240,
      n_users: 8,
      n_user_ask_clusters: 12,
      n_deterministic_clusters: 4,
    },
    ...over,
  };
}

describe("RunProgress", () => {
  it("shows live WIP stats while running", () => {
    render(
      <RunProgress job={job()} onBackToSetup={() => undefined} />,
    );
    expect(screen.getByTestId("run-progress-wip-stats")).toBeInTheDocument();
    expect(screen.getByTestId("wip-stat-users")).toHaveTextContent("8");
    expect(screen.getByTestId("wip-stat-user-ask patterns")).toHaveTextContent("12");
    expect(screen.getByText(/Work in progress/i)).toBeInTheDocument();
  });

  it("hides WIP stats when none are present", () => {
    render(
      <RunProgress
        job={job({ stats: null, message: "Waiting for worker…" })}
        onBackToSetup={() => undefined}
      />,
    );
    expect(screen.queryByTestId("run-progress-wip-stats")).not.toBeInTheDocument();
  });
});
