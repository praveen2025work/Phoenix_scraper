import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test } from "vitest";
import { ThemeToggle } from "./ThemeToggle";

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

test("clicking the toggle flips data-theme", async () => {
  render(<ThemeToggle />);
  const before = document.documentElement.dataset.theme;
  await userEvent.click(screen.getByRole("button", { name: /toggle theme/i }));
  expect(document.documentElement.dataset.theme).not.toBe(before);
  expect(["light", "dark"]).toContain(document.documentElement.dataset.theme);
});
