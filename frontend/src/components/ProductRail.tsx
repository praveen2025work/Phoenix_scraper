import { Link } from "react-router-dom";
import {
  JOURNEY_STEPS,
  type JourneyStep,
  useJourney,
} from "@/journey/JourneyContext";
import { cn } from "@/lib/utils";

const HINT: Record<JourneyStep, string> = {
  Capabilities: "Pick scope",
  Setup: "Window & skills",
  Run: "Scrape & match",
  Gaps: "What skills miss",
  Decide: "Promote or harden",
  History: "Past versions",
};

/** Deep-link targets for when a capability is known but detail isn't mounted. */
export function journeyStepPath(
  step: JourneyStep,
  capabilityId: string,
): string | null {
  switch (step) {
    case "Capabilities":
      return "/";
    case "Setup":
      return `/c/${capabilityId}?step=setup`;
    case "Gaps":
      return `/c/${capabilityId}?step=results`;
    case "Decide":
      return `/c/${capabilityId}?step=results&focus=decide`;
    case "History":
      return `/c/${capabilityId}?step=history`;
    case "Run":
      return null;
  }
}

function disabledReason(
  step: JourneyStep,
  capabilityId: string | null,
): string | null {
  if (step === "Capabilities") return null;
  if (!capabilityId) return "Open a capability first";
  if (step === "Run") return "Start a run from Setup → Run now";
  return null;
}

/** Persistent product journey rail — always shows the guided loop. */
export function ProductRail() {
  const { current, handlers, capabilityId } = useJourney();
  const idx = JOURNEY_STEPS.indexOf(current);

  return (
    <nav
      aria-label="Product journey"
      data-testid="product-rail"
      className="product-rail relative z-0 border-b border-border bg-rail px-2 py-2 md:border-b-0 md:border-r md:px-2 md:py-3"
    >
      <p className="mb-1.5 hidden px-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground md:block">
        Journey
      </p>
      <ol className="flex gap-0.5 overflow-x-auto md:flex-col md:gap-0.5 md:overflow-visible">
        {JOURNEY_STEPS.map((step, i) => {
          const active = step === current;
          const done = i < idx;
          const reason = disabledReason(step, capabilityId);
          const inPage = !!handlers.onSelect && !!capabilityId && step !== "Run";
          const href =
            !reason && !inPage && capabilityId
              ? journeyStepPath(step, capabilityId)
              : step === "Capabilities"
                ? "/"
                : null;
          const className = cn(
            "journey-step flex min-w-[6.5rem] flex-col rounded-md border px-2 py-1.5 text-left transition-[background-color,border-color] duration-150 md:min-w-0",
            active && "border-primary bg-background text-foreground shadow-sm",
            !active && done && "border-transparent bg-background/50 text-foreground",
            !active &&
              !done &&
              "border-transparent text-muted-foreground hover:bg-background/40",
            reason && "cursor-not-allowed opacity-60 hover:bg-transparent",
          );
          const body = (
            <>
              <span className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold tabular-nums",
                    active
                      ? "bg-primary text-primary-foreground"
                      : done
                        ? "bg-accent text-foreground"
                        : "bg-muted text-muted-foreground",
                  )}
                >
                  {i + 1}
                </span>
                <span className={cn("text-sm", active ? "font-semibold" : "font-medium")}>
                  {step}
                </span>
              </span>
              <span className="mt-0.5 pl-[1.375rem] text-[11px] leading-tight text-muted-foreground">
                {HINT[step]}
              </span>
            </>
          );

          if (step === "Capabilities") {
            return (
              <li key={step}>
                <Link
                  to="/"
                  className={className}
                  aria-current={active ? "step" : undefined}
                >
                  {body}
                </Link>
              </li>
            );
          }

          if (inPage && handlers.onSelect) {
            return (
              <li key={step}>
                <button
                  type="button"
                  className={className}
                  aria-label={step}
                  aria-current={active ? "step" : undefined}
                  onClick={() => handlers.onSelect?.(step)}
                >
                  {body}
                </button>
              </li>
            );
          }

          if (href) {
            return (
              <li key={step}>
                <Link
                  to={href}
                  className={className}
                  aria-label={step}
                  aria-current={active ? "step" : undefined}
                >
                  {body}
                </Link>
              </li>
            );
          }

          return (
            <li key={step}>
              <span
                className={cn(className, "cursor-not-allowed")}
                aria-label={step}
                aria-disabled="true"
                aria-current={active ? "step" : undefined}
                title={reason ?? undefined}
                data-disabled-reason={reason ?? undefined}
              >
                {body}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
