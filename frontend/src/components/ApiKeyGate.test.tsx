import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test } from "vitest";
import { ApiKeyGate } from "./ApiKeyGate";

afterEach(() => sessionStorage.clear());

test("blocks until a key is entered, then reveals children", async () => {
  render(
    <ApiKeyGate>
      <div>secret dashboard</div>
    </ApiKeyGate>,
  );
  expect(screen.queryByText("secret dashboard")).not.toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("API key"), "abc");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByText("secret dashboard")).toBeInTheDocument();
  expect(sessionStorage.getItem("pheonix_api_key")).toBe("abc");
});
