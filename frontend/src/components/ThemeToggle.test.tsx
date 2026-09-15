import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test } from "vitest";
import { ThemeToggle } from "./ThemeToggle";

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  document.documentElement.classList.remove("dark");
});

test("clicking the toggle flips data-theme and .dark class", async () => {
  render(<ThemeToggle />);
  const before = document.documentElement.dataset.theme;
  const beforeDark = document.documentElement.classList.contains("dark");
  await userEvent.click(screen.getByRole("button", { name: /toggle theme/i }));
  expect(document.documentElement.dataset.theme).not.toBe(before);
  expect(["light", "dark"]).toContain(document.documentElement.dataset.theme);
  expect(document.documentElement.classList.contains("dark")).toBe(!beforeDark);
  expect(document.documentElement.classList.contains("dark")).toBe(
    document.documentElement.dataset.theme === "dark",
  );
});
