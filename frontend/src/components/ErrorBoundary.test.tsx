import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom({ crash }: { crash: boolean }) {
  if (crash) throw new Error("kaboom");
  return <p>fine</p>;
}

test("catches a render error and recovers on Try again", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const { rerender } = render(
    <ErrorBoundary>
      <Boom crash />
    </ErrorBoundary>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("kaboom");

  rerender(
    <ErrorBoundary>
      <Boom crash={false} />
    </ErrorBoundary>,
  );
  await userEvent.click(screen.getByRole("button", { name: /try again/i }));
  expect(screen.getByText("fine")).toBeInTheDocument();
});
