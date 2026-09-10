import { cn } from "@/lib/utils";

const STEPS = ["Setup", "Running", "Results", "History"] as const;

export type WizardStep = (typeof STEPS)[number];

const RUNNING_IDLE_TITLE = "Shown while a run is in progress";

/** Compact in-page step strip — short labels only (capability workflow nav). */
export function WizardSteps({
  current,
  onSelect,
  className,
}: {
  current: WizardStep;
  /** When set, Setup / Results / History become clickable navigation. */
  onSelect?: (step: WizardStep) => void;
  className?: string;
}) {
  const idx = STEPS.indexOf(current);
  return (
    <nav
      aria-label="Run workflow"
      className={cn(
        "flex w-full flex-wrap items-center gap-1 rounded-lg border border-border bg-background/60 p-1",
        className,
      )}
    >
      {STEPS.map((step, i) => {
        const active = i === idx;
        const isRunningMilestone = step === "Running";
        // Running is a progress milestone, not a nav target — never "done"/clickable.
        const done = i < idx && !isRunningMilestone;
        const clickable =
          !!onSelect &&
          !isRunningMilestone &&
          (step === "History" || step === "Setup" || step === "Results");
        const base =
          "min-w-0 flex-1 rounded-md px-2.5 py-1.5 text-center text-sm transition-colors duration-150";
        const tone = isRunningMilestone
          ? active
            ? "bg-background font-semibold text-foreground shadow-sm"
            : "cursor-default font-medium text-muted-foreground/65"
          : active
            ? "bg-background font-semibold text-foreground shadow-sm"
            : done
              ? "font-medium text-foreground/85 hover:bg-background/70"
              : "font-medium text-muted-foreground";
        return clickable ? (
          <button
            key={step}
            type="button"
            className={`${base} ${tone}`}
            aria-label={step}
            aria-current={active ? "step" : undefined}
            onClick={() => onSelect(step)}
          >
            {step}
          </button>
        ) : (
          <span
            key={step}
            className={`${base} ${tone}`}
            aria-label={step}
            aria-current={active ? "step" : undefined}
            aria-disabled={isRunningMilestone && !active ? true : undefined}
            title={
              isRunningMilestone && !active ? RUNNING_IDLE_TITLE : undefined
            }
            data-testid={isRunningMilestone ? "wizard-running-step" : undefined}
          >
            {step}
          </span>
        );
      })}
    </nav>
  );
}
