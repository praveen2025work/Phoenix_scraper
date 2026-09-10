import { useState } from "react";
import type { Candidate } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { CandidateCard } from "./CandidateCard";

const ACTIVE_ORDER = [
  "new",
  "accumulating",
  "insufficient_data",
  "ready",
  "accepted",
  "promoted",
];
const HIDDEN = new Set(["rejected", "snoozed", "stale"]);

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  accumulating: "Building evidence",
  insufficient_data: "Needs more data",
  ready: "Ready to decide",
  accepted: "Accepted",
  promoted: "Promoted",
  rejected: "Rejected",
  snoozed: "Snoozed",
  stale: "Stale",
};

export function LaneBoard({
  candidates,
  capabilityId,
}: {
  candidates: Candidate[];
  capabilityId: string;
}) {
  const [showHidden, setShowHidden] = useState(false);
  const hiddenCount = candidates.filter((c) => HIDDEN.has(c.status)).length;
  const visible = candidates.filter((c) => showHidden || !HIDDEN.has(c.status));

  const byStatus = new Map<string, Candidate[]>();
  for (const c of visible) {
    const list = byStatus.get(c.status) ?? [];
    list.push(c);
    byStatus.set(c.status, list);
  }
  const columns = [...byStatus.keys()].sort((a, b) => {
    const ia = ACTIVE_ORDER.indexOf(a);
    const ib = ACTIVE_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });

  return (
    <div className="space-y-3" data-testid="lane-board" data-capability={capabilityId}>
      {columns.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No candidates in this decision lane yet.
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {columns.map((status) => {
          const label = STATUS_LABEL[status] ?? status;
          const count = byStatus.get(status)!.length;
          return (
            <section key={status} className="space-y-2" data-status={status}>
              <h3 className="text-sm font-semibold text-muted-foreground">
                {label} ({count})
              </h3>
              {byStatus.get(status)!.map((c) => (
                <CandidateCard key={c.candidate_id} candidate={c} />
              ))}
            </section>
          );
        })}
      </div>
      {hiddenCount > 0 && (
        <Button variant="ghost" size="sm" onClick={() => setShowHidden((v) => !v)}>
          {showHidden ? "Hide" : "Show"} rejected / snoozed / stale ({hiddenCount})
        </Button>
      )}
    </div>
  );
}
