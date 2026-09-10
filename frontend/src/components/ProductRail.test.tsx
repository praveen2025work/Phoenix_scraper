import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { ProductRail, journeyStepPath, STORY_STEPS } from "./ProductRail";
import {
  JourneyProvider,
  useJourney,
  type JourneyStep,
} from "@/journey/JourneyContext";
import { useEffect, type ReactNode } from "react";

function SeedJourney({
  capabilityId,
  current,
  onSelect,
  children,
}: {
  capabilityId?: string | null;
  current?: JourneyStep;
  onSelect?: (step: JourneyStep) => void;
  children: ReactNode;
}) {
  const { setCapabilityId, setHandlers, setCurrent } = useJourney();
  useEffect(() => {
    setCapabilityId(capabilityId ?? null);
    setHandlers(onSelect ? { onSelect } : {});
    if (current) setCurrent(current);
  }, [capabilityId, current, onSelect, setCapabilityId, setHandlers, setCurrent]);
  return <>{children}</>;
}

function renderRail(opts: {
  capabilityId?: string | null;
  current?: JourneyStep;
  onSelect?: (step: JourneyStep) => void;
} = {}) {
  return render(
    <MemoryRouter>
      <JourneyProvider>
        <SeedJourney
          capabilityId={opts.capabilityId}
          current={opts.current}
          onSelect={opts.onSelect}
        >
          <ProductRail />
        </SeedJourney>
      </JourneyProvider>
    </MemoryRouter>,
  );
}

test("journeyStepPath maps steps to capability deep-links", () => {
  expect(journeyStepPath("Setup", "fobo")).toBe("/c/fobo?step=setup");
  expect(journeyStepPath("Gaps", "fobo")).toBe("/c/fobo?step=results");
  expect(journeyStepPath("Decide", "fobo")).toBe(
    "/c/fobo?step=results&focus=decide",
  );
  expect(journeyStepPath("History", "fobo")).toBe("/c/fobo?step=history");
  expect(journeyStepPath("Run", "fobo")).toBeNull();
});

test("left rail shows Setup · Run · Gaps · Decide · History", () => {
  renderRail();
  const rail = screen.getByTestId("product-rail");
  expect(rail).toHaveAttribute("data-collapsed", "false");
  expect(screen.getByLabelText("Product journey")).toBeInTheDocument();
  for (const step of STORY_STEPS) {
    expect(screen.getByLabelText(step)).toBeInTheDocument();
  }
  expect(screen.queryByLabelText("Capabilities")).not.toBeInTheDocument();
  expect(rail.textContent).toMatch(/Setup/);
  expect(rail.textContent).toMatch(/Run/);
  expect(rail.textContent).toMatch(/Gaps/);
  expect(rail.textContent).toMatch(/Decide/);
  expect(rail.textContent).toMatch(/History/);
  // Vertical rail — no horizontal journey arrows.
  expect(rail.textContent).not.toMatch(/→/);
});

test("rail collapse toggles and persists preference", () => {
  localStorage.removeItem("phoenix_rail_collapsed");
  renderRail();
  const rail = screen.getByTestId("product-rail");
  expect(rail).toHaveAttribute("data-collapsed", "false");

  fireEvent.click(screen.getByLabelText("Collapse journey rail"));
  expect(rail).toHaveAttribute("data-collapsed", "true");
  expect(localStorage.getItem("phoenix_rail_collapsed")).toBe("1");
  // Labels hidden when collapsed; aria-labels remain.
  expect(rail.textContent).not.toMatch(/Setup/);
  expect(screen.getByLabelText("Setup")).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText("Expand journey rail"));
  expect(rail).toHaveAttribute("data-collapsed", "false");
  expect(localStorage.getItem("phoenix_rail_collapsed")).toBe("0");
});

test("without capability context, story steps are disabled with reasons", () => {
  renderRail();
  const setup = screen.getByLabelText("Setup");
  expect(setup.tagName).toBe("SPAN");
  expect(setup).toHaveAttribute("title", "Open a capability first");
  expect(setup).toHaveAttribute("aria-disabled", "true");

  const run = screen.getByLabelText("Run");
  expect(run).toHaveAttribute("title", "Open a capability first");
});

test("with capability id on home, Setup/Gaps/History deep-link", async () => {
  renderRail({ capabilityId: "fobo" });
  expect(await screen.findByRole("link", { name: "Setup" })).toHaveAttribute(
    "href",
    "/c/fobo?step=setup",
  );
  expect(screen.getByRole("link", { name: "Gaps" })).toHaveAttribute(
    "href",
    "/c/fobo?step=results",
  );
  expect(screen.getByRole("link", { name: "Decide" })).toHaveAttribute(
    "href",
    "/c/fobo?step=results&focus=decide",
  );
  expect(screen.getByRole("link", { name: "History" })).toHaveAttribute(
    "href",
    "/c/fobo?step=history",
  );
  const run = screen.getByLabelText("Run");
  expect(run.tagName).toBe("SPAN");
  expect(run).toHaveAttribute("title", "Shown while a run is in progress");
});

test("with onSelect, Setup uses an in-page button", async () => {
  const onSelect = () => {};
  renderRail({ capabilityId: "fobo", onSelect, current: "Setup" });
  expect(await screen.findByRole("button", { name: "Setup" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Setup" })).toHaveAttribute(
    "aria-current",
    "step",
  );
});
