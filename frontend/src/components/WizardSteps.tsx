const STEPS = ["Setup", "Running", "Results", "History"] as const;

export type WizardStep = (typeof STEPS)[number];

const STEP_HINT: Record<WizardStep, string> = {
  Setup: "Window & skills",
  Running: "Scrape & match",
  Results: "Gaps & decisions",
  History: "Past versions",
};

/** Compact in-page step strip (mirrors product rail phases for this capability). */
export function WizardSteps({
  current,
  onSelect,
}: {
  current: WizardStep;
  /** When set, Setup / Results / History become clickable navigation. */
  onSelect?: (step: WizardStep) => void;
}) {
  const idx = STEPS.indexOf(current);
  return (
    <nav
      aria-label="Run workflow"
      className="flex flex-wrap items-stretch gap-1 rounded-lg border border-border bg-surface p-1"
    >
      {STEPS.map((step, i) => {
        const active = i === idx;
        const done = i < idx && step !== "History";
        const clickable =
          !!onSelect &&
          step !== "Running" &&
          (step === "History" || step === "Setup" || step === "Results");
        const base =
          "flex min-w-[5.25rem] flex-col rounded-md px-2.5 py-1.5 text-left transition-colors duration-150";
        const tone = active
          ? "bg-background text-foreground shadow-sm"
          : done
            ? "text-foreground/85 hover:bg-background/70"
            : "text-muted-foreground";
        const body = (
          <>
            <span className={`text-sm ${active ? "font-semibold" : "font-medium"}`}>
              {step}
            </span>
            <span className="text-[11px] leading-tight text-muted-foreground">
              {STEP_HINT[step]}
            </span>
          </>
        );
        return clickable ? (
          <button
            key={step}
            type="button"
            className={`${base} ${tone}`}
            aria-label={step}
            aria-current={active ? "step" : undefined}
            onClick={() => onSelect(step)}
          >
            {body}
          </button>
        ) : (
          <span
            key={step}
            className={`${base} ${tone}`}
            aria-label={step}
            aria-current={active ? "step" : undefined}
          >
            {body}
          </span>
        );
      })}
    </nav>
  );
}
