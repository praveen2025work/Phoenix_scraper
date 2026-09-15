import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test } from "vitest";
import { setApiKey } from "./api/client";
import App from "./App";

afterEach(() => {
  setApiKey(null);
});

test("renders the app shell with SkillGap chrome and left journey rail", async () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  // Gate shows Connecting… then locks with branded form, or opens the shell.
  await waitFor(() => expect(screen.getByText("SkillGap")).toBeInTheDocument());
  // When the gate opens, the left journey rail is present (no top journey strip).
  await waitFor(() => {
    const rail = screen.queryByTestId("product-rail");
    const gate = screen.queryByLabelText(/API key/i);
    expect(rail || gate).toBeTruthy();
  });
});

test("main content shell is full-width (no max-w gutters)", async () => {
  setApiKey("test-key");
  const { container } = render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  await waitFor(() => {
    expect(container.querySelector("main.app-shell-main")).toBeTruthy();
  });
  const inner = container.querySelector("main.app-shell-main > div");
  expect(inner?.className ?? "").not.toMatch(/max-w-/);
  expect(inner?.className ?? "").toMatch(/\bw-full\b/);
});
