import { afterEach, expect, test, vi } from "vitest";
import { apiKey, fetchJson, resolveApiBase, setApiKey } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

test("attaches X-API-Key from sessionStorage", async () => {
  setApiKey("secret");
  expect(apiKey()).toBe("secret");
  const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ ok: 1 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  await fetchJson("/health");
  const headers = new Headers((spy.mock.calls[0][1] as RequestInit).headers);
  expect(headers.get("X-API-Key")).toBe("secret");
});

test("throws ApiError with status on non-2xx", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ detail: "nope" }), { status: 409 }),
  );
  await expect(fetchJson("/x")).rejects.toMatchObject({ status: 409, detail: "nope" });
});

test("no key stored -> no X-API-Key header", async () => {
  const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("{}", { status: 200 }),
  );
  await fetchJson("/health");
  const headers = new Headers((spy.mock.calls[0][1] as RequestInit).headers);
  expect(headers.has("X-API-Key")).toBe(false);
});

test("resolveApiBase uses LAN hostname when env unset", () => {
  expect(resolveApiBase(undefined, "192.168.1.10")).toBe("http://192.168.1.10:8000");
  expect(resolveApiBase(undefined, "localhost")).toBe("http://127.0.0.1:8000");
  expect(resolveApiBase("http://custom:9000/", "192.168.1.10")).toBe(
    "http://custom:9000",
  );
});
