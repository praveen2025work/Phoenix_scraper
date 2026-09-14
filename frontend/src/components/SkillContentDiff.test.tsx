import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { SkillContentDiff } from "./SkillContentDiff";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

test("renders unified diff with added and removed lines", () => {
  renderWithProviders(
    <SkillContentDiff
      filename="fx-recon-triage.md"
      currentContent={"name: fx-recon-triage\nold_prompt: triage breaks\n"}
      proposedContent={"name: fx-recon-triage\nexample_prompts:\n  - new ask\n"}
    />,
  );
  expect(screen.getByTestId("skill-content-diff")).toBeInTheDocument();
  expect(screen.getByTestId("diff-view-unified")).toBeInTheDocument();
  expect(screen.getByText("Current (uploaded)")).toBeInTheDocument();
  expect(screen.getByText("Proposed (latest)")).toBeInTheDocument();

  const removed = screen.getAllByTestId("diff-line-remove");
  const added = screen.getAllByTestId("diff-line-add");
  expect(removed.some((el) => el.textContent?.includes("old_prompt: triage breaks"))).toBe(true);
  expect(added.some((el) => el.textContent?.includes("example_prompts:"))).toBe(true);
  expect(added.some((el) => el.textContent?.includes("new ask"))).toBe(true);
});
test("copy and download act on proposed content", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  const createObjectURL = vi.fn(() => "blob:mock");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL,
    revokeObjectURL,
  });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

  renderWithProviders(
    <SkillContentDiff
      filename="fx-recon-triage.md"
      currentContent={null}
      proposedContent={"---\nname: fx-recon-triage\n---\nbody\n"}
    />,
  );

  await userEvent.click(screen.getByRole("button", { name: /copy proposed/i }));
  expect(writeText).toHaveBeenCalledWith("---\nname: fx-recon-triage\n---\nbody\n");

  await userEvent.click(screen.getByRole("button", { name: /download/i }));
  expect(createObjectURL).toHaveBeenCalled();
  expect(click).toHaveBeenCalled();
  const anchor = click.mock.instances[0] as HTMLAnchorElement;
  expect(anchor.download).toBe("fx-recon-triage.md");
});

test("empty current shows new-skill empty state", () => {
  renderWithProviders(
    <SkillContentDiff
      filename="new-skill.md"
      currentContent={null}
      proposedContent={"---\nname: new-skill\n---\n"}
    />,
  );
  expect(screen.getByTestId("diff-empty-new")).toHaveTextContent(
    /no current skill file/i,
  );
  expect(screen.getAllByTestId("diff-line-add").length).toBeGreaterThan(0);
});

test("identical content shows unchanged empty state", () => {
  const body = "---\nname: same\n---\n";
  renderWithProviders(
    <SkillContentDiff
      filename="same.md"
      currentContent={body}
      proposedContent={body}
    />,
  );
  expect(screen.getByTestId("diff-empty-identical")).toHaveTextContent(
    /identical/i,
  );
});

test("can switch to side-by-side view with synced panes", async () => {
  renderWithProviders(
    <SkillContentDiff
      filename="fx-recon-triage.md"
      currentContent={"line-a\nline-b\n"}
      proposedContent={"line-a\nline-c\n"}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: /side-by-side/i }));
  const split = screen.getByTestId("diff-view-split");
  expect(split).toBeInTheDocument();
  // True left | right columns — not stacked top/bottom.
  expect(split.className).toMatch(/flex-row/);
  expect(split.className).not.toMatch(/flex-col/);
  expect(split.className).not.toMatch(/grid-cols-1/);
  expect(screen.getByLabelText(/current uploaded/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/proposed latest/i)).toBeInTheDocument();
  expect(screen.getAllByTestId("diff-line-remove").length).toBeGreaterThan(0);
  expect(screen.getAllByTestId("diff-line-add").length).toBeGreaterThan(0);
});
