import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Panel } from "./Panel";

test("shows a skeleton while loading", () => {
  render(
    <Panel title="Coverage" isLoading>
      <p>data</p>
    </Panel>,
  );
  expect(screen.getByTestId("panel-skeleton")).toBeInTheDocument();
  expect(screen.queryByText("data")).not.toBeInTheDocument();
});

test("shows the error message with an alert role", () => {
  render(
    <Panel title="Coverage" error={new Error("boom")}>
      <p>data</p>
    </Panel>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("boom");
});

test("renders children when settled", () => {
  render(
    <Panel title="Coverage">
      <p>data</p>
    </Panel>,
  );
  expect(screen.getByText("data")).toBeInTheDocument();
});
