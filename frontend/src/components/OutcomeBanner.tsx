import { type ReactNode, useState } from "react";
import { cn } from "@/lib/utils";

/** Compact callout for the next step or expected outcome on a screen. */
export function OutcomeBanner({
  title,
  children,
  className,
  emphasis = false,
  dismissible = false,
  dismissKey,
  "data-testid": testId,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  /** Slightly stronger surface for primary framing. */
  emphasis?: boolean;
  /** Optional dismiss control (session-only unless dismissKey is set). */
  dismissible?: boolean;
  /** Persist dismiss in sessionStorage under this key. */
  dismissKey?: string;
  "data-testid"?: string;
}) {
  const storageKey = dismissKey ? `outcome-dismiss:${dismissKey}` : null;
  const [hidden, setHidden] = useState(() => {
    if (!dismissible || !storageKey) return false;
    try {
      return sessionStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  });

  if (hidden) return null;

  const titleId = `outcome-${title.toLowerCase().replace(/\W+/g, "-")}`;

  function dismiss() {
    setHidden(true);
    if (storageKey) {
      try {
        sessionStorage.setItem(storageKey, "1");
      } catch {
        /* ignore */
      }
    }
  }

  return (
    <aside
      className={cn(
        "panel-enter relative border-l-4 border-l-primary",
        emphasis
          ? "section-surface-strong px-3 py-2.5 sm:px-4"
          : "section-surface px-3 py-2",
        className,
      )}
      data-testid={testId}
      aria-labelledby={titleId}
      role="status"
    >
      <div className="flex items-start justify-between gap-2">
        <p
          id={titleId}
          className={cn(
            "font-semibold text-foreground",
            emphasis ? "text-sm" : "text-sm",
          )}
        >
          {title}
        </p>
        {dismissible && (
          <button
            type="button"
            className="shrink-0 text-xs text-muted-foreground hover:text-foreground"
            onClick={dismiss}
            aria-label="Dismiss"
          >
            Dismiss
          </button>
        )}
      </div>
      <div className="mt-0.5 text-sm leading-snug text-muted-foreground">
        {children}
      </div>
    </aside>
  );
}
