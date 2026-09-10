import type { VariantProps } from "class-variance-authority";
import type { badgeVariants } from "@/components/ui/badge";

export type StatusBadgeVariant = NonNullable<
  VariantProps<typeof badgeVariants>["variant"]
>;

/** Candidate workflow statuses → badge variant (tokenized colors). */
const CANDIDATE_STATUS_VARIANT: Record<string, StatusBadgeVariant> = {
  new: "new",
  accumulating: "accumulating",
  insufficient_data: "insufficient",
  ready: "ready",
  accepted: "accepted",
  promoted: "promoted",
  rejected: "rejected",
  snoozed: "snoozed",
  stale: "stale",
};

/** Job / run result statuses → badge variant. */
const JOB_STATUS_VARIANT: Record<string, StatusBadgeVariant> = {
  ok: "ok",
  partial: "partial",
  error: "error",
  failed: "error",
};

/** Column / label text color for lane headers. */
export const STATUS_FG_CLASS: Record<string, string> = {
  new: "text-status-new-fg",
  accumulating: "text-status-accumulating-fg",
  insufficient_data: "text-status-insufficient-fg",
  ready: "text-status-ready-fg",
  accepted: "text-status-accepted-fg",
  promoted: "text-status-promoted-fg",
  rejected: "text-status-rejected-fg",
  snoozed: "text-status-snoozed-fg",
  stale: "text-status-stale-fg",
};

export function candidateStatusVariant(status: string): StatusBadgeVariant {
  return CANDIDATE_STATUS_VARIANT[status] ?? "outline";
}

export function jobStatusVariant(status: string | null | undefined): StatusBadgeVariant {
  if (!status) return "outline";
  return JOB_STATUS_VARIANT[status] ?? "outline";
}

export function statusBadgeVariant(status: string): StatusBadgeVariant {
  return (
    CANDIDATE_STATUS_VARIANT[status] ??
    JOB_STATUS_VARIANT[status] ??
    "outline"
  );
}
