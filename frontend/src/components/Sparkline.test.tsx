import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Sparkline } from "./Sparkline";

test("renders a polyline for >=2 points", () => {
  const { container } = render(<Sparkline values={[1, 3, 2, 5]} />);
  expect(container.querySelector("polyline")).toBeTruthy();
});

test("renders a dash for <2 points", () => {
  render(<Sparkline values={[1]} />);
  expect(screen.getByText("—")).toBeInTheDocument();
});
