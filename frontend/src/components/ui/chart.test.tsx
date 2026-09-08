import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { AreaSeriesChart, BarSeriesChart } from "./chart";

test("bar chart mounts a recharts wrapper for non-empty data", () => {
  const { container } = render(
    <div style={{ width: 400, height: 220 }}>
      <BarSeriesChart data={[{ label: "a", value: 3 }, { label: "b", value: 5 }]} />
    </div>,
  );
  expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
});

test("area chart mounts a recharts wrapper", () => {
  const { container } = render(
    <div style={{ width: 400, height: 220 }}>
      <AreaSeriesChart data={[{ label: "d1", value: 12 }, { label: "d2", value: 20 }]} />
    </div>,
  );
  expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
});
