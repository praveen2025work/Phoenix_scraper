import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { FilterEditor } from "./FilterEditor";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const json = (b: unknown) =>
  new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });

const PREVIEW = {
  n_spans: 57, n_llm_spans: 41, n_users: 7, n_sessions: 20, n_spans_in_store: 388,
  window_days: 30,
  distinct: { workflow_stage: ["fobo_recon"], asset_class: ["fx"], project: ["pnl-agent"] },
  sample_prompts: ["why is there a recon break of 100k on EURUSD"],
};

function mock(preview: unknown = PREVIEW) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const p = new URL(String(url), "http://x").pathname;
    if (p === "/capabilities/preview" && init?.method === "POST") return json(preview);
    if (p === "/capabilities/fobo" && init?.method === "PATCH") return json({ capability: {} });
    return new Response("null", { status: 404 });
  });
}

test("previews the current filter and shows the counts and samples", async () => {
  mock();
  renderWithProviders(
    <FilterEditor capabilityId="fobo" initial={{ workflow_stage: "fobo_recon" }} windowDays={30} />,
  );
  await waitFor(() => expect(screen.getByText("57")).toBeInTheDocument());
  expect(screen.getByText(/\/ 388 spans/)).toBeInTheDocument();
  expect(screen.getByText("fobo_recon")).toBeInTheDocument();
  expect(screen.getByText(/why is there a recon break/)).toBeInTheDocument();
});

test("preview caps sample prompts at three", async () => {
  mock({
    ...PREVIEW,
    sample_prompts: ["one", "two", "three", "four", "five"],
  });
  renderWithProviders(
    <FilterEditor capabilityId="fobo" initial={{}} windowDays={30} />,
  );
  await waitFor(() => expect(screen.getByText("one")).toBeInTheDocument());
  expect(screen.getByText("three")).toBeInTheDocument();
  expect(screen.queryByText("four")).not.toBeInTheDocument();
});

test("typing patterns sends them as search_any", async () => {
  const spy = mock();
  renderWithProviders(<FilterEditor capabilityId="fobo" initial={{}} windowDays={30} />);
  await userEvent.type(
    screen.getByLabelText(/search any patterns/i),
    "recon break{Enter}unmatched",
  );
  await waitFor(
    () => {
      const post = spy.mock.calls
        .filter(([u, i]) =>
          String(u).endsWith("/capabilities/preview") && (i as RequestInit).method === "POST")
        .pop();
      expect(post).toBeTruthy();
      const body = JSON.parse((post![1] as RequestInit).body as string);
      expect(body.filter.search_any).toEqual(["recon break", "unmatched"]);
    },
    { timeout: 3000 },
  );
});

test("an empty match is called out, not shown as a bare zero", async () => {
  mock({ ...PREVIEW, n_spans: 0, n_llm_spans: 0, sample_prompts: [], distinct: { workflow_stage: [], asset_class: [], project: [] } });
  renderWithProviders(<FilterEditor capabilityId="fobo" initial={{}} windowDays={30} />);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/nothing matches/i));
});

test("Save filter PATCHes the capability", async () => {
  const spy = mock();
  renderWithProviders(<FilterEditor capabilityId="fobo" initial={{}} windowDays={30} />);
  await userEvent.click(screen.getByRole("button", { name: /save filter/i }));
  await waitFor(() =>
    expect(
      spy.mock.calls.some(
        ([u, i]) =>
          String(u).endsWith("/capabilities/fobo") && (i as RequestInit).method === "PATCH",
      ),
    ).toBe(true),
  );
});
