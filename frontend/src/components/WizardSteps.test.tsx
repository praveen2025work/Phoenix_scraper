import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { WizardSteps } from "./WizardSteps";

test("Setup / Results / History navigate; Running is idle milestone", async () => {
  const onSelect = vi.fn();
  render(<WizardSteps current="Results" onSelect={onSelect} />);

  const nav = screen.getByRole("navigation", { name: /Run workflow/i });
  expect(within(nav).getByRole("button", { name: /^Setup$/i })).toBeInTheDocument();
  expect(within(nav).getByRole("button", { name: /^Results$/i })).toBeInTheDocument();
  expect(within(nav).getByRole("button", { name: /^History$/i })).toBeInTheDocument();
  expect(
    within(nav).queryByRole("button", { name: /^Running$/i }),
  ).not.toBeInTheDocument();

  const running = screen.getByTestId("wizard-running-step");
  expect(running.tagName).toBe("SPAN");
  expect(running).toHaveAttribute(
    "title",
    "Shown while a run is in progress",
  );
  expect(running).toHaveAttribute("aria-disabled", "true");

  await userEvent.click(within(nav).getByRole("button", { name: /^History$/i }));
  expect(onSelect).toHaveBeenCalledWith("History");
});

test("Running active has no idle title; other steps stay clickable", () => {
  const onSelect = vi.fn();
  render(<WizardSteps current="Running" onSelect={onSelect} />);

  const running = screen.getByTestId("wizard-running-step");
  expect(running).not.toHaveAttribute("title");
  expect(running).not.toHaveAttribute("aria-disabled");
  expect(screen.getByRole("button", { name: /^Setup$/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Results$/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^History$/i })).toBeInTheDocument();
});
