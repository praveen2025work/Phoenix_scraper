import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api/client";
import {
  type Observation,
  useCandidate,
  useCapability,
  useDecide,
  usePromote,
} from "@/api/hooks";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { PageHeader } from "@/components/PageHeader";
import { Sparkline } from "@/components/Sparkline";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { useJourney } from "@/journey/JourneyContext";
import { cn } from "@/lib/utils";

// Mirrors ladder.DECISION_TRANSITIONS: action -> statuses it is allowed from.
const ALLOWED: Record<string, string[]> = {
  accept: ["ready"],
  reject: ["accumulating", "ready", "new"],
  snooze: ["accumulating", "ready", "new"],
  reopen: ["rejected", "snoozed", "stale"],
};

const ACTION_LABEL: Record<string, string> = {
  accept: "Accept",
  reject: "Reject",
  snooze: "Snooze",
  reopen: "Reopen",
};

/** Settings defaults when capability.thresholds omits a key (see config.py). */
const DEFAULT_THRESHOLDS = {
  rung1_min_count: 15,
  rung1_min_users: 3,
  rung1_sustained_runs: 5,
  rung2_sustained_runs: 3,
};

type LadderThresholds = {
  rung1_min_count: number;
  rung1_min_users: number;
  rung1_sustained_runs: number;
  rung2_sustained_runs: number;
};

function resolveThresholds(raw: Record<string, unknown> | undefined): LadderThresholds {
  const n = (key: keyof typeof DEFAULT_THRESHOLDS) => {
    const v = raw?.[key];
    return typeof v === "number" && Number.isFinite(v) ? v : DEFAULT_THRESHOLDS[key];
  };
  return {
    rung1_min_count: n("rung1_min_count"),
    rung1_min_users: n("rung1_min_users"),
    rung1_sustained_runs: n("rung1_sustained_runs"),
    rung2_sustained_runs: n("rung2_sustained_runs"),
  };
}

/** Why Accept is blocked beyond status — prefer concrete bar failures over generic copy. */
function acceptEvidenceHint(
  status: string,
  observations: Observation[],
  thresholds: LadderThresholds,
  rung: string,
): string | null {
  if (status !== "new" && status !== "accumulating") return null;
  const latest = observations.at(-1);
  if (!latest) {
    return status === "new"
      ? "Still new — run analysis so evidence can accumulate."
      : "Still accumulating — run analysis so evidence can meet the bar.";
  }
  const sustained =
    rung === "deterministic"
      ? thresholds.rung2_sustained_runs
      : thresholds.rung1_sustained_runs;
  if (!latest.met_evidence_bar) {
    if (rung === "deterministic") {
      return "Latest run did not meet the determinism evidence bar.";
    }
    const parts: string[] = [];
    if (latest.count < thresholds.rung1_min_count) {
      parts.push(
        `count ${latest.count} < required ${thresholds.rung1_min_count}`,
      );
    }
    const users = latest.n_users;
    if (users != null && users < thresholds.rung1_min_users) {
      parts.push(`users ${users} < required ${thresholds.rung1_min_users}`);
    }
    if (parts.length > 0) {
      return `Latest run ${parts.join(", ")}.`;
    }
    return "Latest run did not meet the evidence bar.";
  }
  let streak = 0;
  for (let i = observations.length - 1; i >= 0; i--) {
    if (!observations[i].met_evidence_bar) break;
    streak += 1;
  }
  if (streak < sustained) {
    return `Evidence bar met on latest run — need ${sustained} consecutive runs (currently ${streak}).`;
  }
  return status === "new"
    ? "Still new — run again until evidence sustains."
    : "Still accumulating — need more consecutive runs meeting the evidence bar.";
}

/** Why a decision button is disabled — shown as title/tooltip and next to Accept. */
function actionDisabledReason(
  action: string,
  status: string,
  opts?: {
    observations?: Observation[];
    thresholds?: LadderThresholds;
    rung?: string;
  },
): string | null {
  if (ALLOWED[action]?.includes(status)) return null;
  if (action === "accept") {
    const hint = acceptEvidenceHint(
      status,
      opts?.observations ?? [],
      opts?.thresholds ?? resolveThresholds(undefined),
      opts?.rung ?? "skill",
    );
    if (hint) return `Accept requires status ready. ${hint}`;
    return `Accept requires status ready (current: ${status}).`;
  }
  return `${ACTION_LABEL[action] ?? action} is not available from status “${status}”.`;
}

const SIGNAL_KEYS = [
  "template_concentration",
  "route_invariance",
  "output_self_similarity",
  "slot_stability",
] as const;

const SIGNAL_LABEL: Record<(typeof SIGNAL_KEYS)[number], string> = {
  template_concentration: "Template concentration",
  route_invariance: "Route invariance",
  output_self_similarity: "Answer similarity",
  slot_stability: "Slot stability",
};

function decisionLane(rung: string): string {
  return rung === "deterministic" ? "Make deterministic" : "Promote to skill";
}

function writeCtaLabel(rung: string): string {
  return rung === "deterministic" ? "Write deterministic draft" : "Write skill file";
}

function writePanelTitle(rung: string, capabilityLabel: string): string {
  return rung === "deterministic"
    ? `Write deterministic draft into ${capabilityLabel}`
    : `Write skill draft into ${capabilityLabel}`;
}

function skillsFolderHint(capabilityId: string, rung: string): string {
  const folder = rung === "deterministic" ? "deterministic" : "skills";
  return `capabilities/${capabilityId}/${folder}/`;
}

type LadderStep = 1 | 2 | 3;

function ladderStepFromStatus(status: string): LadderStep {
  if (status === "promoted") return 3;
  if (status === "accepted") return 2;
  return 1;
}

const LADDER_STEPS: { step: LadderStep; label: string; hint: string }[] = [
  { step: 1, label: "Decide", hint: "Accept = decision" },
  { step: 2, label: "Write file", hint: "Materialize the draft" },
  { step: 3, label: "Review folder", hint: "Edit, then run next" },
];

function LadderStepIndicator({ current }: { current: LadderStep }) {
  return (
    <nav
      aria-label="Candidate workflow"
      className="flex flex-wrap items-stretch gap-1 rounded-lg border border-border bg-surface p-1"
    >
      {LADDER_STEPS.map(({ step, label, hint }) => {
        const active = step === current;
        const done = step < current;
        return (
          <span
            key={step}
            className={cn(
              "flex min-w-[6.5rem] flex-1 flex-col rounded-md px-2.5 py-1.5 text-left",
              active
                ? "bg-background text-foreground shadow-sm"
                : done
                  ? "text-foreground/85"
                  : "text-muted-foreground",
            )}
            aria-current={active ? "step" : undefined}
          >
            <span className={`text-sm ${active ? "font-semibold" : "font-medium"}`}>
              Step {step} {label}
            </span>
            <span className="text-[11px] text-muted-foreground">{hint}</span>
          </span>
        );
      })}
    </nav>
  );
}

export function CandidateDetail() {
  const { id = "", cid = "" } = useParams();
  const { setCapabilityId } = useJourney();
  const q = useCandidate(cid);
  const capQ = useCapability(id);
  const decide = useDecide(cid, id);
  const promote = usePromote(cid, id);
  const [dialogAction, setDialogAction] = useState<string | null>(null);
  const [actor, setActor] = useState("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<{ path: string; body: string }[] | null>(null);
  const [writtenPaths, setWrittenPaths] = useState<string[] | null>(null);
  const promotePanelRef = useRef<HTMLElement | null>(null);
  const prevStatusRef = useRef<string | null>(null);

  useEffect(() => {
    setCapabilityId(id);
  }, [id, setCapabilityId]);

  // Reset ephemeral write/preview state when navigating between candidates.
  useEffect(() => {
    setWrittenPaths(null);
    setPreview(null);
    prevStatusRef.current = null;
  }, [cid]);

  const status = q.data?.candidate.status;
  useEffect(() => {
    if (!status) return;
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    if (status === "accepted" && prev !== "accepted") {
      requestAnimationFrame(() => {
        const el = promotePanelRef.current;
        if (!el) return;
        if (typeof el.scrollIntoView === "function") {
          el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        if (typeof el.focus === "function") {
          el.focus({ preventScroll: true });
        }
      });
    }
  }, [status]);

  if (q.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (q.error || !q.data)
    return <p className="text-sm text-destructive">{(q.error as Error)?.message ?? "not found"}</p>;

  const { candidate, observations, decisions } = q.data;
  const isDet = candidate.rung === "deterministic";
  const trend = observations.map((o) => o.score ?? o.count);
  const latestSignals = (observations.at(-1)?.signals ?? {}) as Record<string, number>;
  const lane = decisionLane(candidate.rung);
  const capabilityLabel =
    (capQ.data?.capability as { name?: string } | undefined)?.name?.trim() ||
    id.toUpperCase();
  const thresholds = resolveThresholds(
    (capQ.data?.capability as { thresholds?: Record<string, unknown> } | undefined)
      ?.thresholds,
  );
  const acceptOpts = {
    observations,
    thresholds,
    rung: candidate.rung,
  };
  const acceptBlockedReason = actionDisabledReason(
    "accept",
    candidate.status,
    acceptOpts,
  );
  const ladderStep = ladderStepFromStatus(candidate.status);
  const canWrite = candidate.status === "accepted";
  const isPromoted = candidate.status === "promoted";
  const storedPaths = candidate.promoted_artifact_paths ?? [];
  const successPaths =
    writtenPaths ?? (isPromoted ? (storedPaths.length > 0 ? storedPaths : ["(path unavailable)"]) : null);
  const writeLabel = writeCtaLabel(candidate.rung);
  const folderHint = skillsFolderHint(id, candidate.rung);

  function submitDecision(e: FormEvent) {
    e.preventDefault();
    if (!dialogAction) return;
    decide.mutate(
      { action: dialogAction, actor: actor || undefined, note },
      {
        onSuccess: () => {
          toast.success(`${dialogAction}ed`);
          setDialogAction(null);
          setNote("");
        },
        onError: (err) => toast.error((err as Error).message),
      },
    );
  }

  async function showPreview() {
    try {
      const r = await api.get<{ contents: { path: string; body: string }[] }>(
        `/candidates/${encodeURIComponent(cid)}/artifact/preview`,
      );
      setPreview(r.contents);
    } catch (err) {
      toast.error((err as Error).message);
    }
  }

  function doPromote() {
    promote.mutate(false, {
      onSuccess: (r) => {
        setWrittenPaths(r.paths);
        toast.success(`Wrote ${r.paths.length} file(s)`);
      },
      onError: (err) => toast.error((err as Error).message),
    });
  }

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={
          <Link to={`/c/${id}?step=results`} className="hover:underline">
            Results
          </Link>
        }
        title={candidate.title || candidate.candidate_id}
        outcome={
          <>
            {lane}:{" "}
            {candidate.status === "ready"
              ? "Accept first, then write the file."
              : candidate.status === "accepted"
                ? "Accepted — write the draft next."
                : candidate.status === "promoted"
                  ? "File written — review folder, then run next version."
                  : "Review evidence, then accept / reject / snooze."}
          </>
        }
        meta={
          <div className="flex flex-wrap gap-1">
            <Badge>{lane}</Badge>
            {candidate.subtype && <Badge variant="outline">{candidate.subtype}</Badge>}
            <StatusBadge status={candidate.status} />
            {candidate.matched_skill && (
              <Badge variant="outline">→ {candidate.matched_skill}</Badge>
            )}
          </div>
        }
      />

      <LadderStepIndicator current={ladderStep} />

      <OutcomeBanner title="Next" dismissible dismissKey={`cand-next-${cid}`}>
        {successPaths && successPaths.length > 0 ? (
          <>
            File written under <code>{folderHint}</code>. Edit, then Results or Setup for
            the next version. No need to close other runs.
          </>
        ) : candidate.status === "ready" ? (
          <>
            Accept = decision (no file yet). Then write under <code>{folderHint}</code>.
          </>
        ) : candidate.status === "accepted" ? (
          <>
            Write the {isDet ? "deterministic" : "skill"} draft (step 2). Preview optional.
          </>
        ) : (
          <>When status is ready: Accept, then Write skill file.</>
        )}
      </OutcomeBanner>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3 text-base">
            Evidence trend <Sparkline values={trend} />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <THead>
              <TR>
                <TH>run</TH>
                <TH>count</TH>
                <TH>score</TH>
                <TH>met bar</TH>
              </TR>
            </THead>
            <TBody>
              {observations.map((o) => (
                <TR key={o.run_id}>
                  <TD>{o.run_id.slice(0, 16)}</TD>
                  <TD>{o.count}</TD>
                  <TD>{o.score == null ? "—" : o.score.toFixed(2)}</TD>
                  <TD>{o.met_evidence_bar ? "✓" : ""}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      {isDet && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Determinism signals (latest run)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {SIGNAL_KEYS.map((k) => {
              const v = latestSignals[k];
              return (
                <div key={k} className="flex items-center gap-2 text-sm">
                  <span className="w-48 text-muted-foreground">{SIGNAL_LABEL[k]}</span>
                  <div className="h-2 flex-1 rounded bg-muted">
                    <div
                      className="h-2 rounded bg-primary"
                      style={{ width: `${Math.round((v ?? 0) * 100)}%` }}
                    />
                  </div>
                  <span className="w-10 text-right tabular-nums">
                    {v == null ? "n/a" : v.toFixed(2)}
                  </span>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Step 1 · Decide</CardTitle>
          <p className="text-sm text-muted-foreground">
            Accept = decision only — does not write a file. Reject / snooze removes it
            from the active board.
          </p>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          {Object.keys(ALLOWED).map((action) => {
            const reason = actionDisabledReason(action, candidate.status, acceptOpts);
            return (
              <Button
                key={action}
                size={action === "accept" ? "lg" : "default"}
                variant={
                  action === "reject"
                    ? "destructive"
                    : action === "accept"
                      ? "default"
                      : "outline"
                }
                disabled={!!reason}
                title={reason ?? undefined}
                onClick={() => setDialogAction(action)}
              >
                {ACTION_LABEL[action] ?? action}
              </Button>
            );
          })}
          {acceptBlockedReason && (
            <p className="basis-full text-sm text-muted-foreground">{acceptBlockedReason}</p>
          )}
          {candidate.status === "accepted" && (
            <p className="basis-full text-sm text-muted-foreground">
              Accepted — continue to step 2 to write the file.
            </p>
          )}
        </CardContent>
      </Card>

      <section
        ref={promotePanelRef}
        id="promote-panel"
        tabIndex={-1}
        className={cn(
          "panel-enter space-y-3 rounded-lg border border-border p-4 outline-none",
          canWrite && !successPaths
            ? "section-surface-strong border-l-4 border-l-primary"
            : "section-surface",
        )}
        aria-labelledby="promote-panel-title"
      >
        {successPaths && successPaths.length > 0 ? (
          <>
            <div>
              <h2
                id="promote-panel-title"
                className="font-display text-lg font-semibold tracking-tight text-foreground"
              >
                {isDet ? "Deterministic draft written" : "Skill draft written"}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Edit the file, then Run next version to validate.
              </p>
            </div>
            <ul className="space-y-0.5 rounded-md border border-border bg-background/70 px-2.5 py-1.5 text-sm">
              {successPaths.map((p) => (
                <li key={p} className="font-mono text-xs sm:text-sm">
                  {p}
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2">
              <Button asChild size="lg">
                <Link to={`/c/${id}?step=results`}>Back to Results</Link>
              </Button>
              <Button asChild variant="outline">
                <Link to={`/c/${id}?step=setup`}>Setup skills</Link>
              </Button>
            </div>
          </>
        ) : (
          <>
            <div>
              <h2
                id="promote-panel-title"
                className="font-display text-lg font-semibold tracking-tight text-foreground"
              >
                {writePanelTitle(candidate.rung, capabilityLabel)}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Creates/updates a markdown{" "}
                {isDet ? "deterministic draft" : "skill file"} under{" "}
                <code>{folderHint}</code>.
              </p>
            </div>
            {!canWrite && (
              <p className="text-sm font-medium text-foreground">
                First accept, then you can write the file.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                size="lg"
                disabled={!canWrite || promote.isPending}
                onClick={doPromote}
              >
                {writeLabel}
              </Button>
              <Button variant="outline" onClick={showPreview}>
                Preview files first
              </Button>
            </div>
            {preview?.map((f) => (
              <details key={f.path} className="rounded border border-border bg-background/60">
                <summary className="cursor-pointer px-2 py-1 text-sm text-muted-foreground">
                  {f.path}
                </summary>
                <pre className="overflow-x-auto p-2 text-xs">{f.body}</pre>
              </details>
            ))}
          </>
        )}
      </section>

      {decisions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Decision log</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm text-muted-foreground">
            {decisions.map((d, i) => (
              <p key={i}>
                {d.created_at.slice(0, 16)} · {d.action} by {d.actor}{" "}
                {d.note && `— ${d.note}`}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      <Dialog open={!!dialogAction} onOpenChange={(o) => !o && setDialogAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {ACTION_LABEL[dialogAction ?? ""] ?? dialogAction} candidate
            </DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={submitDecision}>
            <label className="block text-sm font-medium">
              actor
              <Input
                aria-label="actor"
                value={actor}
                onChange={(e) => setActor(e.target.value)}
                className="mt-1"
              />
            </label>
            <label className="block text-sm font-medium">
              note
              <Input
                aria-label="note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="mt-1"
              />
            </label>
            <div className="flex justify-end gap-2">
              <DialogClose asChild>
                <Button type="button" variant="ghost">
                  Cancel
                </Button>
              </DialogClose>
              <Button type="submit" size="lg" disabled={decide.isPending}>
                Confirm
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
