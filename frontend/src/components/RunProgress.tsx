import type { JobDto } from "@/api/hooks";
import { OutcomeBanner } from "@/components/OutcomeBanner";
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

export function RunProgress({
  job,
  onBackToSetup,
}: {
  job: JobDto | undefined;
  onBackToSetup: () => void;
}) {
  const stage = job?.stage ?? "queued";
  const progress = Math.max(0, Math.min(1, job?.progress ?? 0));
  const pct = Math.round(progress * 100);
  const errored = job?.state === "error" || stage === "error";
  const message = job?.message || (errored ? job?.error : null) || "Waiting for worker…";
  const currentIdx = stageIndex(stage);

  return (
    <div className="space-y-5" data-testid="run-progress">
      <OutcomeBanner title={errored ? "Something went wrong" : "Next step"}>
        {errored
          ? "Fix the issue below, then return to Setup and run again."
          : "Stay on this screen until the version is ready — Results will open automatically."}
      </OutcomeBanner>

      <Panel
        title={errored ? "Run failed" : "Finding questions your skills miss…"}
        subtitle="Scrape → cluster → match against uploaded skill files"
      >
        <div className="space-y-5">
          <ol className="flex flex-wrap gap-2" aria-label="run stages">
            {STAGE_ORDER.map((s, i) => {
              const active = !errored && i === currentIdx;
              const past = !errored && i < currentIdx;
              return (
                <li key={s}>
                  <Badge variant={active ? "default" : past ? "outline" : "outline"}>
                    <span className="tabular-nums text-muted-foreground">{i + 1}.</span>{" "}
                    {STAGE_LABEL[s]}
                    {s === stage ? ` (${s})` : ""}
                  </Badge>
                </li>
              );
            })}
            {errored && <Badge variant="warn">error</Badge>}
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

          {job?.error && errored && (
            <p className="text-sm text-destructive" role="alert">
              {job.error}
            </p>
          )}

          {errored && (
            <Button size="lg" variant="outline" onClick={onBackToSetup}>
              Back to Setup
            </Button>
          )}
        </div>
      </Panel>
    </div>
  );
}
