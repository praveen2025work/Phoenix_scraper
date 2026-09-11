import { useMemo } from "react";
import {
  type CapabilityRunRow,
  useCapabilityRuns,
} from "@/api/hooks";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  calendarDay,
  formatHumanDate,
  formatHumanDateTime,
  formatWeekLabel,
  weekStartDay,
} from "@/lib/dates";

interface DayGroup {
  day: string;
  week: string;
  showWeekHeader: boolean;
  runs: CapabilityRunRow[];
}

function groupByDay(runs: CapabilityRunRow[]): DayGroup[] {
  const map = new Map<string, CapabilityRunRow[]>();
  for (const run of runs) {
    const day =
      calendarDay(run.run_id) ||
      calendarDay(run.finished_at) ||
      calendarDay(run.started_at) ||
      "unknown";
    const list = map.get(day) ?? [];
    list.push(run);
    map.set(day, list);
  }
  const sorted = [...map.entries()].sort(([a], [b]) => b.localeCompare(a));
  let lastWeek = "";
  return sorted.map(([day, dayRuns]) => {
    const week = day === "unknown" ? "unknown" : weekStartDay(day);
    const showWeekHeader = week !== "unknown" && week !== lastWeek;
    if (showWeekHeader) lastWeek = week;
    return { day, week, showWeekHeader, runs: dayRuns };
  });
}

export function RunHistory({
  capabilityId,
  selectedRunId,
  onSelectRun,
  onNewRun,
}: {
  capabilityId: string;
  selectedRunId?: string | null;
  onSelectRun: (runId: string) => void;
  onNewRun?: () => void;
}) {
  const { data, isLoading, error } = useCapabilityRuns(capabilityId);
  const groups = useMemo(() => groupByDay(data ?? []), [data]);
  const latestRunId = data?.[0]?.run_id ?? null;

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading history…</p>;
  }
  if (error) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {(error as Error).message}
      </p>
    );
  }

  if (!data?.length) {
    return (
      <div className="space-y-3 rounded-md border border-border p-4" data-testid="run-history">
        <h2 className="text-lg font-semibold tracking-tight">No versions yet</h2>
        <p className="text-sm text-muted-foreground">
          Run a closed window once — each run becomes a browsable version.
        </p>
        {onNewRun && (
          <Button size="lg" onClick={onNewRun}>
            Go to Setup
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="run-history">
      <header className="space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-0.5">
            <h2 className="font-display text-xl font-semibold tracking-tight sm:text-2xl">
              Version history
            </h2>
            <p className="text-sm text-muted-foreground">
              Same-day versions don&apos;t block each other. Promote candidates anytime;
              History is for comparison.
            </p>
          </div>
          {onNewRun && (
            <Button size="lg" onClick={onNewRun}>
              Run a new version
            </Button>
          )}
        </div>
        <OutcomeBanner
          title="Versions"
          dismissible
          dismissKey={`history-tip-${capabilityId}`}
        >
          Each Run now is an independent version. Latest opens by default; older runs are
          snapshots — decisions still apply to the live candidate. No need to close prior
          runs.
        </OutcomeBanner>
      </header>

      <div className="space-y-3">
        {groups.map((g) => (
          <section
            key={g.day}
            aria-labelledby={`hist-day-${g.day}`}
            className="section-surface p-3"
          >
            {g.showWeekHeader && (
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {formatWeekLabel(g.week)}
              </p>
            )}
            <h3
              id={`hist-day-${g.day}`}
              className="mb-1.5 text-sm font-semibold text-foreground"
            >
              {g.day === "unknown"
                ? "Unknown day"
                : formatHumanDate(`${g.day}T12:00:00.000Z`)}
            </h3>
            <ul className="divide-y divide-border rounded-md border border-border">
              {g.runs.map((run) => {
                const selected = run.run_id === selectedRunId;
                const isLatest = run.run_id === latestRunId;
                return (
                  <li key={run.run_id}>
                    <button
                      type="button"
                      data-testid={`history-run-${run.run_id}`}
                      aria-current={selected ? "true" : undefined}
                      onClick={() => onSelectRun(run.run_id)}
                      className={`flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 px-3 py-2 text-left text-sm transition-colors hover:bg-muted/50 ${
                        selected ? "bg-muted/60" : ""
                      }`}
                    >
                      <span className="font-medium">
                        {formatHumanDateTime(run.run_id)}
                      </span>
                      {isLatest && (
                        <StatusBadge status="latest" data-testid="history-latest-badge">
                          Latest
                        </StatusBadge>
                      )}
                      <StatusBadge status={run.status ?? "—"}>
                        {run.status ?? "—"}
                      </StatusBadge>
                      <span className="text-xs text-muted-foreground">
                        {formatHumanDate(run.window_start)} →{" "}
                        {formatHumanDate(run.window_end)}
                      </span>
                      <span className="ml-auto text-xs text-muted-foreground">
                        {run.n_clusters ?? 0} clusters ·{" "}
                        {run.n_rung1_candidates ?? 0} promote ·{" "}
                        {run.n_rung2_candidates ?? 0} deterministic
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
