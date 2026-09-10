import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { useCapability, useEnqueueRun, useJob, useSkillFiles } from "@/api/hooks";
import { FilterEditor } from "@/components/FilterEditor";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { PageHeader } from "@/components/PageHeader";
import { RunHistory } from "@/components/RunHistory";
import { RunProgress } from "@/components/RunProgress";
import { RunResults } from "@/components/RunResults";
import { SkillFiles } from "@/components/SkillFiles";
import { WizardSteps, type WizardStep } from "@/components/WizardSteps";
import { Badge } from "@/components/ui/badge";
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

  // Keep the app-wide product rail in sync with this capability's step.
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

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumb={
          <Link to="/" className="hover:underline">
            Capabilities
          </Link>
        }
        title={summary?.name ?? id}
        outcome={
          <>
            Gaps first — then{" "}
            <span className="text-foreground">promote to skill</span> or{" "}
            <span className="text-foreground">make deterministic</span>.
          </>
        }
        meta={
          summary && (
            <p className="flex flex-wrap items-center gap-2">
              <span>
                {Object.entries(summary.filter)
                  .filter(([, v]) => (Array.isArray(v) ? v.length : v))
                  .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("|") : v}`)
                  .join(", ") || "all spans"}
              </span>
              <Badge variant={summary.status === "active" ? "default" : "warn"}>
                {summary.status}
              </Badge>
            </p>
          )
        }
        actions={<WizardSteps current={step} onSelect={onWizardSelect} />}
      />

      {step === "Setup" && (
        <div className="step-enter space-y-4" data-testid="run-setup">
          <OutcomeBanner title="Expected outcome" data-testid="setup-howto" dismissible dismissKey={`setup-${id}`}>
            Closed window + skill MDs → Run now → gaps & promotion queue. Same-day
            versions don&apos;t block each other.
          </OutcomeBanner>

          <section className="section-surface space-y-3 p-4">
            <div>
              <h2 className="font-display text-lg font-semibold tracking-tight">
                1. Pick window
              </h2>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Closed from/to required. Default last {DEFAULT_WINDOW_DAYS} days —
                keep short; large backfills may truncate.
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-sm font-medium text-foreground">
                From
                <Input
                  type="date"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                  aria-label="window start date"
                  className="mt-1 h-10 w-44"
                  required
                />
              </label>
              <label className="text-sm font-medium text-foreground">
                To
                <Input
                  type="date"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                  aria-label="window end date"
                  className="mt-1 h-10 w-44"
                  required
                />
              </label>
              <Button
                size="lg"
                onClick={triggerRun}
                disabled={running || !from || !to}
              >
                {enqueue.isPending ? "Starting…" : "3. Run now"}
              </Button>
              {(resultRunId || lastRunId) && (
                <Button variant="ghost" onClick={goHistory}>
                  Browse history
                </Button>
              )}
            </div>
          </section>

          <section className="section-surface space-y-3 p-4">
            <div>
              <h2 className="font-display text-lg font-semibold tracking-tight">
                2. Upload skills ({skillCount})
              </h2>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Hashes freeze at run start — edit, re-upload same filename, re-run.
              </p>
            </div>
            <SkillFiles capabilityId={id} />
          </section>

          <details className="section-surface p-4">
            <summary className="cursor-pointer font-display text-base font-semibold tracking-tight">
              Advanced filter
            </summary>
            <p className="mt-1 text-sm text-muted-foreground">
              Optional. Empty = no narrowing. Preview uses the same from/to.
            </p>
            <div className="mt-3">
              <FilterEditor
                capabilityId={id}
                initial={(summary?.filter ?? {}) as Record<string, never>}
                windowDays={DEFAULT_WINDOW_DAYS}
                windowFrom={from || undefined}
                windowTo={to || undefined}
              />
            </div>
          </details>
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
            onBrowseHistory={goHistory}
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
