import { Link, useParams, useSearchParams } from "react-router-dom";
import { useEffect, type ReactNode } from "react";
import { useCapability, useRunAnalytics } from "@/api/hooks";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { useJourney } from "@/journey/JourneyContext";
import { BehaviourSection } from "./analytics/BehaviourSection";
import { CoverageSection } from "./analytics/CoverageSection";
import { GlanceStrip, Headline } from "./analytics/Headline";
import { QualitySection } from "./analytics/QualitySection";
import { AnalyticsSnapshotProvider } from "./analytics/snapshotContext";

const DAY = /^(\d{4}-\d{2}-\d{2})/;

/** The API scopes every panel to the last run's window, so say which one that is —
 *  an unlabelled date range is how "the dashboard is empty" becomes unanswerable. */
function periodLabel(run: Record<string, unknown> | null, windowDays: number): string {
  const from = DAY.exec(String(run?.window_start ?? ""))?.[1];
  const to = DAY.exec(String(run?.window_end ?? ""))?.[1];
  return from && to
    ? `${from} → ${to} (this version's window)`
    : `last ${windowDays} days (no run yet)`;
}

export function Analytics() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const { setCapabilityId } = useJourney();
  const cap = useCapability(id);
  const summary = cap.data?.summary;
  const name = summary?.name ?? id;
  const lastRun = (summary?.last_run as Record<string, unknown> | null) ?? null;
  const runId =
    params.get("run") ||
    (lastRun?.run_id != null ? String(lastRun.run_id) : null);
  const lastStatus = String(lastRun?.status ?? "");
  const runCompleted =
    Boolean(params.get("run")) ||
    lastStatus === "ok" ||
    lastStatus === "partial";
  // NOTE: snapshotReady reads from the capability summary's last_run, not from the
  // specific run referenced by ?run=. When run-history deep-linking ships, derive
  // this from the viewed run's own analytics_ready field (e.g. via useRunResults).
  // snapshotReady follows last_run today; when ?run= deep-links to older versions,
  // resolve readiness for that run_id instead of always using last_run.
  const snapshotReady = Boolean(lastRun?.analytics_ready);
  const analytics = useRunAnalytics(id, runId, !!runId && snapshotReady);

  useEffect(() => {
    setCapabilityId(id);
  }, [id, setCapabilityId]);

  const showWaiting = !runId || (!snapshotReady && !runCompleted);
  const snapshot =
    snapshotReady && analytics.data && !analytics.isError ? analytics.data : null;
  const showLoading = !showWaiting && snapshotReady && analytics.isLoading && !snapshot;
  const period = periodLabel(lastRun, summary?.window_days ?? 30);

  const chrome = (glance: ReactNode = null) => (
    <section
      className="section-surface space-y-1.5 p-3 sm:p-4"
      data-testid="analytics-chrome"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <Link
          to={`/c/${id}`}
          className="text-xs font-medium text-muted-foreground hover:underline"
        >
          ← Results
        </Link>
        <span aria-hidden className="text-xs text-border">
          ·
        </span>
        <span className="min-w-0 truncate text-xs font-medium text-muted-foreground">
          {name}
        </span>
        <span aria-hidden className="text-xs text-border">
          ·
        </span>
        <h1 className="font-display text-xl font-semibold leading-tight tracking-tight text-foreground sm:text-2xl">
          Usage for this version
        </h1>
      </div>
      <p className="text-[11px] leading-snug text-muted-foreground">{period}</p>
      {glance}
    </section>
  );

  return (
    <div className="space-y-5">
      {showWaiting ? (
        <>
          {chrome()}
          <OutcomeBanner title="Usage not ready yet" data-testid="analytics-waiting">
            Available after a run finishes. Return to Results and run a version —
            Usage unlocks when the analytics snapshot is ready.
          </OutcomeBanner>
        </>
      ) : showLoading ? (
        <>
          {chrome()}
          <p className="text-sm text-muted-foreground">Loading usage…</p>
        </>
      ) : (
        <AnalyticsSnapshotProvider value={snapshot}>
          {chrome(<GlanceStrip id={id} />)}
          <Headline id={id} />
          <CoverageSection id={id} />
          <QualitySection id={id} />
          <BehaviourSection id={id} />
        </AnalyticsSnapshotProvider>
      )}
    </div>
  );
}
