import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { ProductRail, journeyStepPath } from "./ProductRail";
import {
  JourneyProvider,
  useJourney,
  type JourneyStep,
} from "@/journey/JourneyContext";
import { useEffect, type ReactNode } from "react";

function SeedJourney({
  capabilityId,
  onSelect,
  children,
}: {
  capabilityId?: string | null;
  onSelect?: (step: JourneyStep) => void;
  children: ReactNode;
}) {
  const { setCapabilityId, setHandlers } = useJourney();
  useEffect(() => {
    setCapabilityId(capabilityId ?? null);
    setHandlers(onSelect ? { onSelect } : {});
  }, [capabilityId, onSelect, setCapabilityId, setHandlers]);
  return <>{children}</>;
}

function renderRail(opts: {
  capabilityId?: string | null;
  onSelect?: (step: JourneyStep) => void;
} = {}) {
  return render(
    <MemoryRouter>
      <JourneyProvider>
        <SeedJourney capabilityId={opts.capabilityId} onSelect={opts.onSelect}>
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

test("without capability context, rail steps are disabled with reasons", () => {
  renderRail();
  expect(screen.getByRole("link", { name: /Capabilities/i })).toHaveAttribute(
    "href",
    "/",
  );
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
  expect(run).toHaveAttribute("title", "Start a run from Setup → Run now");
});

test("with onSelect, Setup uses an in-page button", async () => {
  const onSelect = () => {};
  renderRail({ capabilityId: "fobo", onSelect });
  expect(await screen.findByRole("button", { name: "Setup" })).toBeInTheDocument();
});
