import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Shared page chrome: display title, one-line outcome, optional actions. */
export function PageHeader({
  title,
  outcome,
  breadcrumb,
  actions,
  meta,
  className,
}: {
  title: ReactNode;
  /** Short outcome-oriented framing — what this screen is for. */
  outcome?: ReactNode;
  breadcrumb?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3",
        className,
      )}
    >
      <div className="min-w-0 max-w-3xl space-y-1">
        {breadcrumb && (
          <p className="text-xs font-medium text-muted-foreground">{breadcrumb}</p>
        )}
        <h1 className="font-display text-2xl font-semibold leading-tight tracking-tight text-foreground sm:text-3xl">
          {title}
        </h1>
        {outcome && (
          <p
            className="max-w-2xl text-sm leading-snug text-muted-foreground"
            data-testid="outcome-framing"
          >
            {outcome}
          </p>
        )}
        {meta && <div className="text-xs text-muted-foreground">{meta}</div>}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">{actions}</div>
      )}
    </header>
  );
}
