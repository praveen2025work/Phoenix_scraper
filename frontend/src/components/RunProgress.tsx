import type { JobDto, JobProgressStats } from "@/api/hooks";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/Panel";

const STAGE_ORDER = ["queued", "scraping", "analyzing", "matching", "done"] as const;

const STAGE_LABEL: Record<(typeof STAGE_ORDER)[number], string> = {
  queued: "Queued",
  scraping: "Scraping",
  analyzing: "Clustering",
  matching: "Matching skills",
  done: "Done",
};

function stageIndex(stage: string): number {
  const i = STAGE_ORDER.indexOf(stage as (typeof STAGE_ORDER)[number]);
  return i >= 0 ? i : 0;
}

function Stat({ label, value }: { label: string; value: number | string | undefined }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <li
      className="rounded-md border border-border/80 bg-background/60 px-3 py-2"
      data-testid={`wip-stat-${label}`}
    >
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular-nums text-foreground">{value}</p>
    </li>
  );
}

function formatMs(ms: number | undefined): string | undefined {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return undefined;
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function WipStats({ stats }: { stats: JobProgressStats | null | undefined }) {
  if (!stats) return null;
  const items: { label: string; value: number | string | undefined }[] = [
    { label: "spans in scope", value: stats.n_in_scope },
    { label: "users", value: stats.n_users },
    { label: "turns", value: stats.n_turns },
    { label: "avg turn", value: formatMs(stats.avg_turn_ms) },
    { label: "avg thinking", value: formatMs(stats.avg_thinking_ms) },
    { label: "avg tools/queries", value: formatMs(stats.avg_tool_ms) },
    {
      label: "bottleneck thinking %",
      value: stats.pct_bottleneck_thinking,
    },
    {
      label: "bottleneck tools %",
      value: stats.pct_bottleneck_tool,
    },
    { label: "user-ask patterns", value: stats.n_user_ask_clusters },
    { label: "tool / MCP patterns", value: stats.n_deterministic_clusters },
    { label: "skills matched", value: stats.n_matched },
    { label: "covered", value: stats.n_covered },
    { label: "promote to skill", value: stats.n_rung1 },
    { label: "make deterministic", value: stats.n_rung2 },
  ];
  const visible = items.filter((i) => i.value !== undefined);
  if (!visible.length) return null;
  return (
    <ul
      className="grid grid-cols-2 gap-2 sm:grid-cols-4"
      data-testid="run-progress-wip-stats"
      aria-label="work in progress counts"
    >
      {visible.map((i) => (
        <Stat key={i.label} label={i.label} value={i.value} />
      ))}
    </ul>
  );
}

export function RunProgress({
  job,
  onBackToSetup,
  onCancel,
  cancelPending = false,
}: {
  job: JobDto | undefined;
  onBackToSetup: () => void;
  onCancel?: () => void;
  cancelPending?: boolean;
}) {
  const stage = job?.stage ?? "queued";
  const progress = Math.max(0, Math.min(1, job?.progress ?? 0));
  const pct = Math.round(progress * 100);
  const cancelled = job?.error === "cancelled";
  const errored = job?.state === "error" || stage === "error";
  const message = job?.message || (errored ? job?.error : null) || "Waiting for worker…";
  const currentIdx = stageIndex(stage);
  const canCancel =
    !!onCancel && !!job && (job.state === "queued" || job.state === "running");
  const active = !cancelled && !errored && job?.state !== "done";

  return (
    <div className="space-y-5" data-testid="run-progress">
      <OutcomeBanner
        title={
          cancelled
            ? "Run cancelled"
            : errored
              ? "Something went wrong"
              : active
                ? "Work in progress"
                : "Next step"
        }
      >
        {cancelled
          ? "Return to Setup when you want to run again."
          : errored
            ? "Fix the issue below, then return to Setup and run again."
            : "Counts update as each stage finishes. Results open automatically when the version is ready."}
      </OutcomeBanner>

      <Panel
        title={
          cancelled
            ? "Cancelled"
            : errored
              ? "Run failed"
              : "Finding patterns your skills miss…"
        }
        subtitle="Scrape → cluster similar asks & tool calls → match skills → Decide queue"
      >
        <div className="space-y-5">
          <ol className="flex flex-wrap gap-2" aria-label="run stages">
            {STAGE_ORDER.map((s, i) => {
              const activeStage = !errored && i === currentIdx;
              const past = !errored && i < currentIdx;
              return (
                <li key={s}>
                  <Badge
                    variant={activeStage ? "info" : past ? "ok" : "outline"}
                    className="uppercase tracking-wide"
                  >
                    <span className="tabular-nums opacity-80">{i + 1}.</span>{" "}
                    {STAGE_LABEL[s]}
                    {s === stage ? ` (${s})` : ""}
                  </Badge>
                </li>
              );
            })}
            {errored && <StatusBadge status="error" />}
          </ol>

          <div
            className="h-2.5 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="run progress"
          >
            <div
              className={`h-full transition-all ${errored ? "bg-destructive" : "bg-foreground"}`}
              style={{ width: `${errored ? 100 : pct}%` }}
            />
          </div>

          <p className="text-base" role="status">
            {message}
          </p>

          <WipStats stats={job?.stats} />

          {job?.error && errored && (
            <p className="text-sm text-destructive" role="alert">
              {job.error}
            </p>
          )}

          <div className="flex flex-wrap gap-3">
            {canCancel && (
              <Button
                size="lg"
                variant="outline"
                disabled={cancelPending}
                onClick={onCancel}
                data-testid="cancel-run"
              >
                {cancelPending ? "Cancelling…" : "Cancel run"}
              </Button>
            )}
            {errored && (
              <Button size="lg" variant="outline" onClick={onBackToSetup}>
                Back to Setup
              </Button>
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}
