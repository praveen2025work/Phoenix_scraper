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
];
const COLLAPSED_BY_DEFAULT = new Set(["promoted"]);
const HIDDEN = new Set(["rejected", "snoozed", "stale"]);

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  accumulating: "Building evidence",
  insufficient_data: "Needs more data",
  ready: "Ready",
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
  const [showPromoted, setShowPromoted] = useState(false);

  const hiddenCount = candidates.filter((c) => HIDDEN.has(c.status)).length;
  const promotedCount = candidates.filter((c) => c.status === "promoted").length;

  const visible = candidates.filter((c) => {
    if (HIDDEN.has(c.status)) return showHidden;
    if (COLLAPSED_BY_DEFAULT.has(c.status)) return showPromoted;
    return true;
  });

  const byStatus = new Map<string, Candidate[]>();
  for (const c of visible) {
    const list = byStatus.get(c.status) ?? [];
    list.push(c);
    byStatus.set(c.status, list);
  }
  const columns = [...byStatus.keys()].sort((a, b) => {
    const ia = ACTIVE_ORDER.indexOf(a);
    const ib = ACTIVE_ORDER.indexOf(b);
    const oa = ia < 0 ? (a === "promoted" ? 50 : 99) : ia;
    const ob = ib < 0 ? (b === "promoted" ? 50 : 99) : ib;
    return oa - ob;
  });

  return (
    <div className="space-y-3" data-testid="lane-board" data-capability={capabilityId}>
      {columns.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {promotedCount > 0 || hiddenCount > 0
            ? "No active candidates — expand promoted or hidden below."
            : "No candidates in this decision lane yet."}
        </p>
      )}
      <div className="space-y-3">
        {columns.map((status) => {
          const label = STATUS_LABEL[status] ?? status;
          const count = byStatus.get(status)!.length;
          return (
            <section key={status} className="space-y-1.5" data-status={status}>
              <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {label}{" "}
                <span className="tabular-nums">· {count}</span>
              </h4>
              <div className="space-y-1.5">
                {byStatus.get(status)!.map((c) => (
                  <CandidateCard key={c.candidate_id} candidate={c} />
                ))}
              </div>
            </section>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-2">
        {promotedCount > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground"
            aria-pressed={showPromoted}
            onClick={() => setShowPromoted((v) => !v)}
            data-testid="toggle-promoted"
          >
            {showPromoted ? "Hide" : "Show"} promoted ({promotedCount})
          </Button>
        )}
        {hiddenCount > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground"
            aria-pressed={showHidden}
            onClick={() => setShowHidden((v) => !v)}
          >
            {showHidden ? "Hide" : "Show"} rejected / snoozed / stale ({hiddenCount})
          </Button>
        )}
      </div>
    </div>
  );
}
