import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { SkillContentDiff } from "./SkillContentDiff";
import { renderWithProviders } from "@/test/renderWithProviders";

afterEach(() => vi.restoreAllMocks());

test("shows left current and right proposed skill markdown", () => {
  renderWithProviders(
    <SkillContentDiff
      filename="fx-recon-triage.md"
      currentContent={"---\nname: fx-recon-triage\n---\n"}
      proposedContent={"---\nname: fx-recon-triage\nexample_prompts:\n  - new ask\n---\n"}
    />,
  );
  expect(screen.getByTestId("skill-content-diff")).toBeInTheDocument();
  expect(screen.getByLabelText(/current uploaded/i)).toHaveTextContent("name: fx-recon-triage");
  expect(screen.getByLabelText(/proposed/i)).toHaveTextContent("new ask");
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

test("empty current shows placeholder on the left", () => {
  renderWithProviders(
    <SkillContentDiff
      filename="new-skill.md"
      currentContent={null}
      proposedContent={"---\nname: new-skill\n---\n"}
    />,
  );
  expect(screen.getByLabelText(/current uploaded/i)).toHaveTextContent(
    /no uploaded skill file yet/i,
  );
});
