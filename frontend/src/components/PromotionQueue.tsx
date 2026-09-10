import { Link } from "react-router-dom";
import { type Candidate, useCandidates } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";

function laneLabel(rung: string): string {
  return rung === "deterministic" ? "Make deterministic" : "Promote to skill";
}

function writeHint(rung: string): string {
  return rung === "deterministic"
    ? "Write deterministic draft"
    : "Write skill file";
}

function QueueGroup({
  title,
  hint,
  items,
  capabilityId,
  empty,
  emphasize,
}: {
  title: string;
  hint: string;
  items: Candidate[];
  capabilityId: string;
  empty: string;
  emphasize?: boolean;
}) {
  return (
    <div
      className={
        emphasize
          ? "rounded-md border border-primary/30 bg-surface-strong/80 p-3"
          : "rounded-md border border-border p-3"
      }
    >
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <h4 className="text-sm font-semibold text-foreground">{title}</h4>
        <Badge variant={emphasize ? "ready" : "outline"}>{items.length}</Badge>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground" role="status">
          {empty}
        </p>
      ) : (
        <ul className="divide-y divide-border rounded border border-border/80 bg-background/60">
          {items.map((c) => (
            <li key={c.candidate_id}>
              <Link
                to={`/c/${capabilityId}/candidate/${encodeURIComponent(c.candidate_id)}`}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-2.5 py-1.5 text-sm hover:bg-muted/40"
              >
                <span className="min-w-0 flex-1 font-medium truncate">
                  {c.title || c.candidate_id}
                </span>
                <span className="text-xs text-muted-foreground">
                  {laneLabel(c.rung)}
                  {c.status === "accepted" ? ` · ${writeHint(c.rung)}` : ""}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Live capability promotion queue — Accept ≠ write; decisions persist across runs. */
export function PromotionQueue({ capabilityId }: { capabilityId: string }) {
  const { data, isLoading, error } = useCandidates(capabilityId);

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="promotion-queue">
        Loading promotion queue…
      </p>
    );
  }
  if (error) {
    return (
      <p className="text-sm text-destructive" role="alert" data-testid="promotion-queue">
        {(error as Error).message}
      </p>
    );
  }

  const all = data ?? [];
  const writeNext = all.filter((c) => c.status === "accepted");
  const promoted = all.filter((c) => c.status === "promoted");
  const ready = all.filter((c) => c.status === "ready");

  return (
    <section
      className="space-y-2"
      data-testid="promotion-queue"
      aria-labelledby="promotion-queue-title"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3
          id="promotion-queue-title"
          className="font-display text-lg font-semibold tracking-tight"
        >
          Promotion queue
        </h3>
        <p className="text-xs text-muted-foreground">
          Accept = decision · Write skill file = materialize draft. No need to close other runs.
        </p>
      </div>
      <div className="grid gap-2 lg:grid-cols-3">
        <QueueGroup
          title="Accepted — write file next"
          hint="Open and write the draft"
          items={writeNext}
          capabilityId={capabilityId}
          empty="None waiting to write."
          emphasize
        />
        <QueueGroup
          title="Promoted (files written)"
          hint="Already on disk"
          items={promoted}
          capabilityId={capabilityId}
          empty="None written yet."
        />
        <QueueGroup
          title="Ready to decide"
          hint="Accept, reject, or snooze"
          items={ready}
          capabilityId={capabilityId}
          empty="None ready yet."
        />
      </div>
    </section>
  );
}
