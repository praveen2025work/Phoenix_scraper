import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  GitBranch,
  History,
  Play,
  Scale,
  Settings2,
} from "lucide-react";
import {
  type JourneyStep,
  useJourney,
} from "@/journey/JourneyContext";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/** Product-story steps shown in the left rail (Capabilities lives on the home link). */
export const STORY_STEPS = [
  "Setup",
  "Run",
  "Gaps",
  "Decide",
  "History",
] as const;

export type StoryStep = (typeof STORY_STEPS)[number];

const RAIL_COLLAPSED_KEY = "phoenix_rail_collapsed";

const STEP_ICONS: Record<StoryStep, typeof Settings2> = {
  Setup: Settings2,
  Run: Play,
  Gaps: GitBranch,
  Decide: Scale,
  History: History,
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
  step: StoryStep,
  capabilityId: string | null,
): string | null {
  if (!capabilityId) return "Open a capability first";
  if (step === "Run") return "Shown while a run is in progress";
  return null;
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Vertical product journey — left app chrome.
 * Capability pages keep WizardSteps for real Setup/Running/Results/History nav.
 */
export function ProductRail() {
  const { current, handlers, capabilityId } = useJourney();
  const idx = STORY_STEPS.indexOf(current as StoryStep);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(RAIL_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  return (
    <aside
      data-testid="product-rail"
      data-collapsed={collapsed ? "true" : "false"}
      className={cn(
        "product-rail sticky top-0 flex h-svh shrink-0 flex-col border-r border-border bg-rail transition-[width] duration-200",
        collapsed ? "w-14" : "w-44",
      )}
    >
      <div
        className={cn(
          "flex items-center border-b border-border px-2 py-2",
          collapsed ? "justify-center" : "justify-end",
        )}
      >
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={collapsed ? "Expand journey rail" : "Collapse journey rail"}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </Button>
      </div>

      <nav aria-label="Product journey" className="product-journey min-h-0 flex-1 px-2 py-3">
        <ol className="flex flex-col gap-1">
          {STORY_STEPS.map((step, i) => {
            const active = step === current;
            const done = idx >= 0 && i < idx;
            const reason = disabledReason(step, capabilityId);
            const inPage =
              !!handlers.onSelect && !!capabilityId && step !== "Run";
            const href =
              !reason && !inPage && capabilityId
                ? journeyStepPath(step, capabilityId)
                : null;
            const Icon = STEP_ICONS[step];
            const className = cn(
              "journey-step inline-flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm font-medium transition-colors duration-150",
              collapsed && "justify-center px-0",
              active && "bg-primary text-primary-foreground shadow-sm",
              !active &&
                done &&
                "text-foreground/80 hover:bg-accent hover:text-foreground",
              !active &&
                !done &&
                "text-muted-foreground hover:bg-accent/70 hover:text-foreground",
              reason && "cursor-not-allowed opacity-50 hover:bg-transparent",
            );
            const label = (
              <>
                <Icon size={16} className="shrink-0" aria-hidden="true" />
                {!collapsed && <span className="truncate">{step}</span>}
              </>
            );

            const item = (() => {
              if (inPage && handlers.onSelect) {
                return (
                  <button
                    type="button"
                    className={className}
                    aria-label={step}
                    aria-current={active ? "step" : undefined}
                    title={collapsed ? step : undefined}
                    onClick={() => handlers.onSelect?.(step)}
                  >
                    {label}
                  </button>
                );
              }
              if (href) {
                return (
                  <Link
                    to={href}
                    className={className}
                    aria-label={step}
                    aria-current={active ? "step" : undefined}
                    title={collapsed ? step : undefined}
                  >
                    {label}
                  </Link>
                );
              }
              return (
                <span
                  className={cn(className, reason && "cursor-not-allowed")}
                  aria-label={step}
                  aria-disabled={reason ? "true" : undefined}
                  aria-current={active ? "step" : undefined}
                  title={reason ?? (collapsed ? step : undefined)}
                  data-disabled-reason={reason ?? undefined}
                >
                  {label}
                </span>
              );
            })();

            return <li key={step}>{item}</li>;
          })}
        </ol>
      </nav>
    </aside>
  );
}
