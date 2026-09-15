import {
  type JobDto,
  useCancelJob,
  useCapabilityJobs,
} from "@/api/hooks";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { formatHumanDateTime } from "@/lib/dates";
import { toast } from "sonner";

function jobIdOf(job: JobDto): string {
  return job.job_id ?? "";
}

function pct(progress: number | undefined): string {
  const p = Math.max(0, Math.min(1, progress ?? 0));
  return `${Math.round(p * 100)}%`;
}

export function JobStatusPanel({
  capabilityId,
  activeJobId,
  onWatchJob,
  onOpenRun,
}: {
  capabilityId: string;
  activeJobId?: string | null;
  onWatchJob?: (jobId: string) => void;
  onOpenRun?: (runId: string) => void;
}) {
  const jobs = useCapabilityJobs(capabilityId);
  const cancel = useCancelJob(capabilityId);

  if (jobs.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading jobs…</p>;
  }
  if (jobs.error) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {(jobs.error as Error).message}
      </p>
    );
  }

  const rows = jobs.data ?? [];
  if (!rows.length) {
    return (
      <div
        className="space-y-3 rounded-md border border-border p-4"
        data-testid="job-status-empty"
      >
        <h2 className="text-lg font-semibold tracking-tight">No jobs yet</h2>
        <p className="text-sm text-muted-foreground">
          Start a run from Setup. Queued and in-progress jobs show here with stage,
          progress, and cancel.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="job-status-panel">
      <OutcomeBanner title="Jobs">
        Live queue for this capability — including runs still processing. Version
        History stays for finished analysis versions only.
      </OutcomeBanner>

      <ul className="divide-y divide-border rounded-md border border-border">
        {rows.map((job) => {
          const id = jobIdOf(job);
          if (!id) return null;
          const active = job.state === "queued" || job.state === "running";
          const watching = activeJobId === id;
          return (
            <li
              key={id}
              className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between"
              data-testid={`job-row-${id}`}
            >
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={job.state} />
                  {job.stage && (
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">
                      {job.stage}
                    </span>
                  )}
                  {active && (
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {pct(job.progress)}
                    </span>
                  )}
                  {watching && (
                    <span className="text-xs font-medium text-foreground">Watching</span>
                  )}
                </div>
                <p className="text-sm text-foreground">
                  {job.message ||
                    (job.state === "error" ? job.error : null) ||
                    "Waiting for worker…"}
                </p>
                {job.stats && (job.state === "queued" || job.state === "running") && (
                  <p
                    className="text-[11px] tabular-nums text-muted-foreground"
                    data-testid={`job-wip-${id}`}
                  >
                    {[
                      job.stats.n_in_scope != null
                        ? `${job.stats.n_in_scope} spans`
                        : null,
                      job.stats.n_user_ask_clusters != null
                        ? `${job.stats.n_user_ask_clusters} ask patterns`
                        : null,
                      job.stats.n_deterministic_clusters != null
                        ? `${job.stats.n_deterministic_clusters} tool patterns`
                        : null,
                      job.stats.n_rung1 != null
                        ? `${job.stats.n_rung1} skill candidates`
                        : null,
                      job.stats.n_rung2 != null
                        ? `${job.stats.n_rung2} det candidates`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                )}
                <p className="text-xs text-muted-foreground">
                  Enqueued {formatHumanDateTime(job.enqueued_at)}
                  {job.finished_at
                    ? ` · Finished ${formatHumanDateTime(job.finished_at)}`
                    : ""}
                  <span className="ml-2 font-mono text-[10px] opacity-70">
                    {id.slice(0, 8)}
                  </span>
                </p>
                {job.error && job.state === "error" && (
                  <p className="text-xs text-destructive" role="alert">
                    {job.error}
                  </p>
                )}
              </div>

              <div className="flex flex-wrap gap-2">
                {active && onWatchJob && (
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid={`job-watch-${id}`}
                    onClick={() => onWatchJob(id)}
                  >
                    Watch
                  </Button>
                )}
                {active && (
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid={`job-cancel-${id}`}
                    disabled={cancel.isPending}
                    onClick={() => {
                      cancel.mutate(id, {
                        onSuccess: () => toast.message("Cancel requested"),
                        onError: (e) => toast.error((e as Error).message),
                      });
                    }}
                  >
                    Cancel
                  </Button>
                )}
                {job.state === "done" && job.run_id && onOpenRun && (
                  <Button
                    size="sm"
                    data-testid={`job-open-${id}`}
                    onClick={() => onOpenRun(job.run_id!)}
                  >
                    Open results
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
