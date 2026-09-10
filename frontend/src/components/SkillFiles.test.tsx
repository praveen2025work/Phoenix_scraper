import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { SkillFiles } from "./SkillFiles";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { "content-type": "application/json" } });

const ROW = {
  filename: "fx-recon-triage.md",
  bytes: 220,
  valid: true,
  name: "fx-recon-triage",
  description: "Triage FX recon breaks.",
  n_example_prompts: 2,
};

function mock(list: unknown[] = [ROW]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const p = new URL(String(url), "http://x").pathname;
    if (p === "/capabilities/fobo/skills" && init?.method === "POST")
      return json(ROW, 201);
    if (p.startsWith("/capabilities/fobo/skills/") && init?.method === "DELETE")
      return json({ deleted: "fx-recon-triage.md" });
    if (p === "/capabilities/fobo/skills") return json(list);
    return new Response("null", { status: 404 });
  });
}

test("lists the capability's skill files", async () => {
  mock();
  renderWithProviders(<SkillFiles capabilityId="fobo" />);
  await waitFor(() => expect(screen.getByText("fx-recon-triage.md")).toBeInTheDocument());
  expect(screen.getByText(/Triage FX recon breaks/)).toBeInTheDocument();
  expect(screen.getByText("fx-recon-triage")).toBeInTheDocument();
});

test("empty state is a single short line", async () => {
  mock([]);
  renderWithProviders(<SkillFiles capabilityId="fobo" />);
  await waitFor(() => expect(screen.getByText(/No skill files yet/)).toBeInTheDocument());
  expect(screen.getByRole("status")).toHaveTextContent(/upload a/);
  expect(screen.queryByText(/cannot tell you what your docs already cover/i)).not.toBeInTheDocument();
});

test("pasting a skill file POSTs filename + content", async () => {
  const spy = mock([]);
  renderWithProviders(<SkillFiles capabilityId="fobo" />);
  await waitFor(() => screen.getByText(/No skill files yet/));

  await userEvent.click(screen.getByText(/Paste skill content/i));
  await userEvent.type(screen.getByLabelText(/skill filename/i), "fx-recon-triage.md");
  await userEvent.type(screen.getByLabelText(/skill file content/i), "---{Enter}name: x{Enter}---");
  await userEvent.click(screen.getByRole("button", { name: /save skill file/i }));

  await waitFor(() => {
    const post = spy.mock.calls.find(
      ([u, i]) =>
        String(u).endsWith("/capabilities/fobo/skills") &&
        (i as RequestInit).method === "POST",
    );
    expect(post).toBeTruthy();
    const body = JSON.parse((post![1] as RequestInit).body as string);
    expect(body.filename).toBe("fx-recon-triage.md");
    expect(body.content).toContain("name: x");
  });
});

test("delete calls the API for that file", async () => {
  const spy = mock();
  renderWithProviders(<SkillFiles capabilityId="fobo" />);
  await waitFor(() => screen.getByText("fx-recon-triage.md"));
  await userEvent.click(screen.getByRole("button", { name: /delete fx-recon-triage\.md/i }));
  await waitFor(() =>
    expect(
      spy.mock.calls.some(
        ([u, i]) =>
          String(u).includes("/capabilities/fobo/skills/fx-recon-triage.md") &&
          (i as RequestInit).method === "DELETE",
      ),
    ).toBe(true),
  );
});
