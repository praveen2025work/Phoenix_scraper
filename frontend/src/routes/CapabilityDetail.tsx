import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  type SpanFilter,
  useCapability,
  useEnqueueRun,
  useJob,
  useSkillFiles,
} from "@/api/hooks";
import { FilterEditor } from "@/components/FilterEditor";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { RunHistory } from "@/components/RunHistory";
import { RunProgress } from "@/components/RunProgress";
import { RunResults, RunResultsChrome } from "@/components/RunResults";
import { SkillFiles } from "@/components/SkillFiles";
import { WizardSteps, type WizardStep } from "@/components/WizardSteps";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type JourneyStep,
  useJourney,
} from "@/journey/JourneyContext";

const DEFAULT_WINDOW_DAYS = 7;

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function defaultWindow(): { from: string; to: string } {
  const to = new Date();
  const from = new Date(Date.now() - DEFAULT_WINDOW_DAYS * 86_400_000);
  return { from: isoDate(from), to: isoDate(to) };
}

function wizardToJourney(step: WizardStep): JourneyStep {
  switch (step) {
    case "Setup":
      return "Setup";
    case "Running":
      return "Run";
    case "Results":
      return "Gaps";
    case "History":
      return "History";
  }
}

function filterOneLiner(filter: Record<string, unknown> | undefined): string {
  if (!filter) return "all spans";
  const parts = Object.entries(filter)
    .filter(([, v]) => (Array.isArray(v) ? v.length : v))
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("|") : v}`);
  return parts.join(", ") || "all spans";
}

export function CapabilityDetail() {
  const { id = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const qc = useQueryClient();
  const { setCurrent, setHandlers, setCapabilityId } = useJourney();
  const cap = useCapability(id);
  const skills = useSkillFiles(id);
  const enqueue = useEnqueueRun(id);

  const defaults = useMemo(() => defaultWindow(), []);
  const [from, setFrom] = useState(defaults.from);
  const [to, setTo] = useState(defaults.to);
  const [jobId, setJobId] = useState<string | null>(null);
  const [resultRunId, setResultRunId] = useState<string | null>(null);
  const [forceSetup, setForceSetup] = useState(false);
  const [forceHistory, setForceHistory] = useState(false);
  const [focusDecide, setFocusDecide] = useState(false);

  const job = useJob(id, jobId);
  const summary = cap.data?.summary;
  // Prefer capability.filter (full model_dump) so Advanced never seeds without
  // project — a missing project + Save would wipe pnl-agent and fall back to
  // PHEONIX_PROJECT on the next run.
  const spanFilter = (cap.data?.capability?.filter ??
    summary?.filter ??
    {}) as SpanFilter;
  const lastRunId =
    summary?.last_run && typeof summary.last_run === "object"
      ? String((summary.last_run as { run_id?: string }).run_id ?? "")
      : "";

  // Seed Results from the capability's last run once loaded (unless Setup/History forced).
  useEffect(() => {
    if (forceSetup || forceHistory || jobId || resultRunId) return;
    if (lastRunId) setResultRunId(lastRunId);
  }, [lastRunId, forceSetup, forceHistory, jobId, resultRunId]);

  useEffect(() => {
    const data = job.data;
    if (!data) return;
    if (data.state === "done" && data.run_id) {
      toast.success(`Version ready — ${new Date(data.run_id).toLocaleString()}`);
      qc.invalidateQueries({ queryKey: ["capability", id] });
      qc.invalidateQueries({ queryKey: ["candidates", id] });
      qc.invalidateQueries({ queryKey: ["run-results", id] });
      qc.invalidateQueries({ queryKey: ["capability-runs", id] });
      qc.invalidateQueries({ queryKey: ["run-analytics", id] });
      setResultRunId(data.run_id);
      setJobId(null);
      setForceSetup(false);
      setForceHistory(false);
      setFocusDecide(false);
    } else if (data.state === "error") {
      toast.error(data.error ?? "Run failed");
    }
  }, [job.data, id, qc]);

  const step: WizardStep = jobId
    ? "Running"
    : forceHistory
      ? "History"
      : resultRunId && !forceSetup
        ? "Results"
        : "Setup";

  const running = enqueue.isPending || (jobId !== null && job.data?.state !== "error");

  function closedWindow(): { from: string; to: string } | null {
    if (!from || !to) return null;
    const start = new Date(`${from}T00:00:00.000Z`);
    const end = new Date(`${to}T23:59:59.999Z`);
    if (!(end.getTime() > start.getTime())) return null;
    return { from: start.toISOString(), to: end.toISOString() };
  }

  function triggerRun() {
    const window = closedWindow();
    if (!window) {
      toast.error("Pick a closed from/to range (to must be after from)");
      return;
    }
    const days =
      (new Date(window.to).getTime() - new Date(window.from).getTime()) / 86_400_000;
    if (days > 30) {
      toast.message("Large window — scrape may truncate; watch Running for warnings");
    }
    enqueue.mutate(window, {
      onSuccess: (d) => {
        setForceSetup(false);
        setForceHistory(false);
        setFocusDecide(false);
        setResultRunId(null);
        setJobId(d.job_id);
      },
      onError: (e) => toast.error((e as Error).message),
    });
  }

  function goSetup() {
    setForceSetup(true);
    setForceHistory(false);
    setFocusDecide(false);
    setJobId(null);
    setResultRunId(null);
  }

  function goHistory() {
    setForceHistory(true);
    setForceSetup(false);
    setFocusDecide(false);
    setJobId(null);
  }

  function openRun(runId: string) {
    setResultRunId(runId);
    setForceHistory(false);
    setForceSetup(false);
    setFocusDecide(false);
    setJobId(null);
  }

  function onWizardSelect(next: WizardStep) {
    if (next === "Setup") goSetup();
    else if (next === "History") goHistory();
    else if (next === "Results") {
      if (resultRunId || lastRunId) {
        setResultRunId(resultRunId || lastRunId);
        setForceSetup(false);
        setForceHistory(false);
        setFocusDecide(false);
      }
    }
  }

  function openResults(decide: boolean) {
    const run = resultRunId || lastRunId;
    if (!run) {
      toast.message("Run once to see gaps — open Setup");
      goSetup();
      return;
    }
    setResultRunId(run);
    setForceSetup(false);
    setForceHistory(false);
    setFocusDecide(decide);
    if (decide) {
      requestAnimationFrame(() => {
        document
          .getElementById("decide-panels")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  function onJourneySelect(next: JourneyStep) {
    if (next === "Setup") goSetup();
    else if (next === "History") goHistory();
    else if (next === "Gaps") openResults(false);
    else if (next === "Decide") openResults(true);
  }

  // Honor rail deep-links (?step=setup|results|history&focus=decide).
  useEffect(() => {
    const stepParam = searchParams.get("step");
    const focus = searchParams.get("focus");
    if (!stepParam && !focus) return;
    // Wait for summary so Results/Decide can resolve lastRunId.
    if (
      (stepParam === "results" || focus === "decide") &&
      (cap.isLoading || (!lastRunId && !resultRunId && !cap.error))
    ) {
      return;
    }
    if (stepParam === "setup") goSetup();
    else if (stepParam === "history") goHistory();
    else if (stepParam === "results") openResults(focus === "decide");
    else if (focus === "decide") openResults(true);
    // Clear so in-page navigation isn't re-applied on every render.
    setSearchParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, searchParams, setSearchParams, cap.isLoading, cap.error, lastRunId, resultRunId]);

  // Keep the app-wide left journey rail in sync with this capability's step.
  useEffect(() => {
    setCapabilityId(id);
  }, [id, setCapabilityId]);

  useEffect(() => {
    const journey =
      step === "Results" && focusDecide ? "Decide" : wizardToJourney(step);
    setCurrent(journey);
    setHandlers({ onSelect: onJourneySelect });
    return () => setHandlers({});
    // Rebind when navigation targets change; handlers close over latest ids.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, id, resultRunId, lastRunId, focusDecide, setCurrent, setHandlers]);

  if (cap.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (cap.error)
    return <p className="text-sm text-destructive">{(cap.error as Error).message}</p>;

  const skillCount = skills.data?.length ?? cap.data?.skill_files?.length ?? 0;
  const title = summary?.name ?? id;
  const filterLine = filterOneLiner(
    spanFilter as Record<string, unknown>,
  );

  return (
    <div className="space-y-5">
      <section
        className="section-surface space-y-3 p-3 sm:p-4"
        data-testid="capability-chrome"
      >
        {/* Row 1: breadcrumb · title · status · filter */}
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <Link
            to="/"
            className="text-xs font-medium text-muted-foreground hover:underline"
          >
            Capabilities
          </Link>
          <span aria-hidden className="text-xs text-border">
            ·
          </span>
          <h1 className="font-display text-xl font-semibold leading-tight tracking-tight text-foreground sm:text-2xl">
            {title}
          </h1>
          {summary && (
            <StatusBadge
              status={summary.status}
              className="px-1.5 py-0 text-[10px]"
              data-testid="capability-status-badge"
            />
          )}
          <span
            className="min-w-0 max-w-full truncate text-[11px] text-muted-foreground sm:max-w-md"
            title={filterLine}
            data-testid="capability-filter-line"
          >
            {filterLine}
          </span>
        </div>

        {/* Row 2: wizard full width */}
        <WizardSteps current={step} onSelect={onWizardSelect} />

        {/* Rows 3–4: Results version + metrics inside the same panel */}
        {step === "Results" && resultRunId && (
          <div className="border-t border-border/70 pt-3">
            <RunResultsChrome
              capabilityId={id}
              runId={resultRunId}
              onRunNext={goSetup}
            />
          </div>
        )}
      </section>

      {step === "Setup" && (
        <div className="step-enter space-y-4" data-testid="run-setup">
          <OutcomeBanner
            title="Setup"
            data-testid="setup-howto"
            dismissible
            dismissKey={`setup-${id}`}
          >
            Window + skills → Run now → gaps & promote. Same-day versions don&apos;t
            block each other.
          </OutcomeBanner>

          <section
            className="section-surface divide-y divide-border/70"
            data-testid="setup-card"
          >
            {/* Window */}
            <div className="space-y-3 p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <h2 className="text-sm font-semibold tracking-tight text-foreground">
                  Window
                </h2>
                <p
                  className="text-[11px] text-muted-foreground"
                  title="Large backfills may truncate — keep the window short."
                >
                  Default last {DEFAULT_WINDOW_DAYS} days
                </p>
              </div>
              <div className="flex flex-wrap items-end gap-5">
                <label className="flex flex-col gap-1.5 text-xs font-medium text-foreground">
                  From
                  <Input
                    type="date"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                    aria-label="window start date"
                    className="h-10 w-44 px-3 py-2"
                    required
                  />
                </label>
                <label className="flex flex-col gap-1.5 text-xs font-medium text-foreground">
                  To
                  <Input
                    type="date"
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                    aria-label="window end date"
                    className="h-10 w-44 px-3 py-2"
                    required
                  />
                </label>
              </div>
            </div>

            {/* Skills */}
            <div className="space-y-2 p-4">
              <h2 className="text-sm font-semibold tracking-tight text-foreground">
                Skills
                <span className="ml-1.5 font-normal text-muted-foreground">
                  ({skillCount})
                </span>
              </h2>
              <SkillFiles capabilityId={id} />
            </div>

            {/* Run — primary action, visually last before Advanced */}
            <div className="flex flex-wrap items-center gap-3 bg-surface-strong/60 p-4">
              <Button
                size="xl"
                onClick={triggerRun}
                disabled={running || !from || !to}
                data-testid="setup-run-now"
              >
                {enqueue.isPending ? "Starting…" : "Run now"}
              </Button>
              {(resultRunId || lastRunId) && (
                <Button variant="outline" onClick={goHistory}>
                  Browse history
                </Button>
              )}
            </div>

            {/* Advanced — collapsed */}
            <details className="group p-4">
              <summary className="cursor-pointer text-sm font-semibold tracking-tight text-foreground">
                Advanced
                <span className="ml-2 font-normal text-[11px] text-muted-foreground">
                  span filter & preview
                </span>
              </summary>
              <div className="mt-3">
                <FilterEditor
                  key={id}
                  capabilityId={id}
                  initial={spanFilter}
                  windowDays={DEFAULT_WINDOW_DAYS}
                  windowFrom={from || undefined}
                  windowTo={to || undefined}
                />
              </div>
            </details>
          </section>
        </div>
      )}

      {step === "Running" && (
        <div className="step-enter">
          <RunProgress
            job={job.data}
            onBackToSetup={() => {
              setJobId(null);
              setForceSetup(true);
              setForceHistory(false);
            }}
          />
        </div>
      )}

      {step === "Results" && resultRunId && (
        <div className="step-enter">
          <RunResults
            capabilityId={id}
            runId={resultRunId}
            onRunNext={goSetup}
            showChrome={false}
          />
        </div>
      )}

      {step === "History" && (
        <div className="step-enter">
          <RunHistory
            capabilityId={id}
            selectedRunId={resultRunId}
            onSelectRun={openRun}
            onNewRun={goSetup}
          />
        </div>
      )}
    </div>
  );
}
