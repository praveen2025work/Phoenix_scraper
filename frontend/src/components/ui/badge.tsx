import * as React from "react";
import { type VariantProps, cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/10 text-foreground",
        outline: "border-border text-muted-foreground",
        ready:
          "border-status-ready-border bg-status-ready text-status-ready-fg",
        warn: "border-status-partial-border bg-status-partial text-status-partial-fg",
        danger:
          "border-status-error-border bg-status-error text-status-error-fg",
        new: "border-status-new-border bg-status-new text-status-new-fg",
        accumulating:
          "border-status-accumulating-border bg-status-accumulating text-status-accumulating-fg",
        insufficient:
          "border-status-insufficient-border bg-status-insufficient text-status-insufficient-fg",
        accepted:
          "border-status-accepted-border bg-status-accepted text-status-accepted-fg",
        promoted:
          "border-status-promoted-border bg-status-promoted text-status-promoted-fg",
        rejected:
          "border-status-rejected-border bg-status-rejected text-status-rejected-fg",
        snoozed:
          "border-status-snoozed-border bg-status-snoozed text-status-snoozed-fg",
        stale:
          "border-status-stale-border bg-status-stale text-status-stale-fg",
        ok: "border-status-ok-border bg-status-ok text-status-ok-fg",
        partial:
          "border-status-partial-border bg-status-partial text-status-partial-fg",
        error:
          "border-status-error-border bg-status-error text-status-error-fg",
        info: "border-status-info-border bg-status-info text-status-info-fg",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export const Badge = ({ className, variant, ...props }: BadgeProps) => (
  <span className={cn(badgeVariants({ variant }), className)} {...props} />
);
export { badgeVariants };
