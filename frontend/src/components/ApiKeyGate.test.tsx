import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { setApiKey } from "@/api/client";
import { ApiKeyGate } from "./ApiKeyGate";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

function mockCapabilities(status: number, body: unknown = []) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
      statusText: status === 401 ? "Unauthorized" : "OK",
    }),
  );
}

test("open API (no key required) skips the gate", async () => {
  mockCapabilities(200, []);
  render(
    <ApiKeyGate>
      <div>secret dashboard</div>
    </ApiKeyGate>,
  );
  await waitFor(() => expect(screen.getByText("secret dashboard")).toBeInTheDocument());
  expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
  expect(sessionStorage.getItem("pheonix_api_key")).toBeNull();
});

test("stored key skips the gate without probing", () => {
  setApiKey("already-set");
  const spy = vi.spyOn(globalThis, "fetch");
  render(
    <ApiKeyGate>
      <div>secret dashboard</div>
    </ApiKeyGate>,
  );
  expect(screen.getByText("secret dashboard")).toBeInTheDocument();
  expect(spy).not.toHaveBeenCalled();
});

test("401 shows the gate; entering a key reveals children", async () => {
  mockCapabilities(401, { detail: "Invalid or missing X-API-Key" });
  render(
    <ApiKeyGate>
      <div>secret dashboard</div>
    </ApiKeyGate>,
  );
  expect(await screen.findByLabelText("API key")).toBeInTheDocument();
  expect(screen.getByText(/requires an X-API-Key/i)).toBeInTheDocument();
  expect(screen.queryByText("secret dashboard")).not.toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("API key"), "abc");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByText("secret dashboard")).toBeInTheDocument();
  expect(sessionStorage.getItem("pheonix_api_key")).toBe("abc");
});

test("network error shows the gate with blank-continue allowed", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
  render(
    <ApiKeyGate>
      <div>secret dashboard</div>
    </ApiKeyGate>,
  );
  expect(await screen.findByLabelText("API key")).toBeInTheDocument();
  expect(screen.getByText(/Can't reach the API/i)).toBeInTheDocument();
  expect(screen.getByText(/leave blank/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByText("secret dashboard")).toBeInTheDocument();
  expect(sessionStorage.getItem("pheonix_api_key")).toBeNull();
});
