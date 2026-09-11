import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  type RunCompareDto,
  type RunResultsDto,
  useCapabilityRuns,
  useRunCompare,
  useRunResults,
} from "@/api/hooks";
import { LaneBoard } from "@/components/LaneBoard";
import { OutcomeBanner } from "@/components/OutcomeBanner";
import { Panel } from "@/components/Panel";
import { PromotionQueue } from "@/components/PromotionQueue";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatHumanDate, formatHumanDateTime } from "@/lib/dates";

function shortHash(h: string): string {
  return h.slice(0, 8);
}

const RUN_STATUS_HINT: Record<string, string> = {
  ok: "Run completed successfully",
  partial: "Finished with truncated scrape or incomplete coverage",
  error: "Run failed",
  failed: "Run failed",
};

/** Version + actions + funnel — embeds in capability chrome panel on Results. */
export function RunResultsChrome({
  capabilityId,
  runId,
  onRunNext,
}: {
  capabilityId: string;
  runId: string;
  onRunNext: () => void;
}) {
  const results = useRunResults(capabilityId, runId);
  const runs = useCapabilityRuns(capabilityId);
  const data = results.data;
  const latestRunId = runs.data?.[0]?.run_id ?? null;
  const isLatest = !latestRunId || latestRunId === runId;
  // Prefer precomputed snapshot; unlock Usage on ok/partial even if snapshot lagged
  // so operators are never stuck (Analytics can live-fallback for missing panels).
  const analyticsReady =
    Boolean(data?.analytics_ready) ||
    data?.status === "ok" ||
    data?.status === "partial";

  if (results.isLoading) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="results-chrome-loading">
        Loading version…
      </p>
    );
  }
  if (results.error || !data) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {(results.error as Error)?.message ?? "No results"}
      </p>
    );
  }

  return (
    <div className="space-y-2" data-testid="results-chrome">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div
          className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1"
          data-testid="version-strip"
        >
          <h2 className="font-display text-base font-semibold tracking-tight sm:text-lg">
            Version · {formatHumanDateTime(data.run_id)}
          </h2>
          {isLatest ? (
            <StatusBadge
              status="latest"
              data-testid="latest-run-badge"
              className="px-1.5 py-0"
            >
              Latest
            </StatusBadge>
          ) : (
            <StatusBadge
              status="older"
              data-testid="older-run-badge"
              className="px-1.5 py-0"
            >
              Older
            </StatusBadge>
          )}
          <span className="text-xs text-muted-foreground sm:text-sm">
            {formatHumanDate(data.window_start)} →{" "}
            {formatHumanDate(data.window_end)}
          </span>
          {data.status !== "ok" && (
            <StatusBadge
              status={data.status}
              className="px-1.5 py-0"
              title={
                RUN_STATUS_HINT[data.status] ?? `Run status: ${data.status}`
              }
              data-testid="run-status-badge"
            >
              {data.status}
            </StatusBadge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="default" onClick={onRunNext}>
            Run next version
          </Button>
          {analyticsReady ? (
            <Button asChild variant="outline" size="default" data-testid="usage-button">
              <Link to={`/c/${capabilityId}/analytics`}>Usage</Link>
            </Button>
          ) : (
            <Button
              variant="outline"
              size="default"
              disabled
              title="Available after a run finishes"
              data-testid="usage-button"
            >
              Usage
            </Button>
          )}
        </div>
      </div>

      {!isLatest && (
        <p
          className="text-xs text-muted-foreground"
          role="status"
          data-testid="older-run-note"
        >
          Older snapshot — decisions still apply live; History is for comparison.
        </p>
      )}

      <FunnelStrip funnel={data.funnel} embedded />

      {Object.keys(data.skill_hashes).length > 0 ? (
        <p className="text-[11px] text-muted-foreground">
          Skills frozen:{" "}
          {Object.entries(data.skill_hashes)
            .map(([f, h]) => `${f} (${shortHash(h)})`)
            .join(", ")}
        </p>
      ) : (
        <OutcomeBanner
          title="No skill files"
          dismissible
          dismissKey={`results-no-skills-${capabilityId}-${runId}`}
          data-testid="no-skills-alert"
        >
          Upload on Setup, then run again.
        </OutcomeBanner>
      )}

      {data.warnings.length > 0 && (
        <div className="space-y-0.5" role="alert">
          {data.warnings.map((w) => (
            <p key={w} className="text-xs text-destructive">
              {w}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export function RunResults({
  capabilityId,
  runId,
  onRunNext,
  showChrome = true,
}: {
  capabilityId: string;
  runId: string;
  onRunNext: () => void;
  /** When false, chrome is rendered by the parent capability panel. */
  showChrome?: boolean;
}) {
  const results = useRunResults(capabilityId, runId);
  const data = results.data;
  const runs = useCapabilityRuns(capabilityId);
  const [compareFrom, setCompareFrom] = useState<string | null>(null);

  // Default compare target to previous_run_id when results load / run changes.
  useEffect(() => {
    setCompareFrom(null);
  }, [runId]);

  const prevId = compareFrom ?? data?.previous_run_id ?? null;
  const compare = useRunCompare(capabilityId, prevId, runId);
  const olderRuns = (runs.data ?? []).filter((r) => r.run_id !== runId);

  if (results.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading results…</p>;
  }
  if (results.error || !data) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {(results.error as Error)?.message ?? "No results"}
      </p>
    );
  }

  const funnel = data.funnel;
  const empty =
    funnel.n_clusters === 0 ||
    (funnel.n_uncovered === 0 &&
      funnel.n_unmatched === 0 &&
      data.rung1_candidates.length === 0 &&
      data.rung2_candidates.length === 0);
  const usingDefaultPrev = !compareFrom && !!data.previous_run_id;

  return (
    <div className="space-y-4" data-testid="run-results">
      {showChrome && (
        <RunResultsChrome
          capabilityId={capabilityId}
          runId={runId}
          onRunNext={onRunNext}
        />
      )}

      <PromotionQueue capabilityId={capabilityId} />

      {olderRuns.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="compare-picker">
          <label htmlFor="compare-from" className="font-medium text-foreground">
            Compare with
          </label>
          <select
            id="compare-from"
            className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            value={prevId ?? ""}
            onChange={(e) => setCompareFrom(e.target.value || null)}
          >
            {!data.previous_run_id && (
              <option value="">Pick a version…</option>
            )}
            {data.previous_run_id && (
              <option value={data.previous_run_id}>
                Since last version ({formatHumanDateTime(data.previous_run_id)})
              </option>
            )}
            {olderRuns
              .filter((r) => r.run_id !== data.previous_run_id)
              .map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {formatHumanDateTime(r.run_id)} · {r.status}
                </option>
              ))}
          </select>
          {!usingDefaultPrev && prevId && (
            <Button variant="ghost" size="sm" onClick={() => setCompareFrom(null)}>
              Reset to last version
            </Button>
          )}
        </div>
      )}

      {prevId && (
        <VersionCompare
          compare={compare.data}
          isLoading={compare.isLoading}
          error={compare.error}
          title={usingDefaultPrev ? "Since last version" : "Version comparison"}
        />
      )}

      <Panel
        title="Skill gaps"
        subtitle="Uncovered questions — edit MD, re-upload same filename, re-run"
        emphasis
      >
        {empty && funnel.empty_reason ? (
          <p className="text-sm text-muted-foreground" role="status">
            {funnel.empty_reason}
            {funnel.empty_at ? ` (empty at ${funnel.empty_at})` : ""}
          </p>
        ) : null}

        {data.suggested_skill_updates.length > 0 && (
          <ul className="mb-3 space-y-2">
            {data.suggested_skill_updates.map((u) => (
              <li
                key={u.source_file}
                className="rounded-md border border-border bg-background/70 p-3 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{u.source_file}</span>
                  <Badge variant="outline">{u.skill_name}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {u.uncovered_asks} asks · {u.n_users} users
                  </span>
                </div>
                <ul className="mt-1.5 space-y-0.5">
                  {u.new_prompts.slice(0, 5).map((p) => (
                    <li key={p} className="truncate font-mono text-xs text-muted-foreground">
                      {p}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}

        {data.uncovered.length > 0 ? (
          <ul className="divide-y divide-border rounded-md border border-border bg-background/50">
            {data.uncovered.map((row) => (
              <li
                key={row.cluster_id}
                className="flex flex-wrap items-baseline gap-2 px-3 py-2 text-sm"
              >
                <span className="min-w-0 flex-1 font-medium">{row.representative}</span>
                <span className="text-xs text-muted-foreground">
                  {row.count} asks · {row.n_users} users
                  {row.source_file ? ` · ${row.source_file}` : ""}
                  {row.status ? ` · ${row.status}` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          !funnel.empty_reason && (
            <p className="text-sm text-muted-foreground" role="status">
              No uncovered prompts for this version.
            </p>
          )
        )}
      </Panel>

      <div id="decide-panels" className="space-y-3">
        <div>
          <h3 className="font-display text-lg font-semibold tracking-tight">Decide</h3>
          <p className="text-sm text-muted-foreground">
            Review evidence by board · actions stay in the queue above
          </p>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <Panel title={`Promote to skill · ${data.rung1_candidates.length}`}>
            {data.rung1_candidates.length === 0 ? (
              <p className="text-sm text-muted-foreground" role="status">
                No skill-promotion candidates yet.
              </p>
            ) : (
              <LaneBoard candidates={data.rung1_candidates} capabilityId={capabilityId} />
            )}
          </Panel>

          <Panel title={`Make deterministic · ${data.rung2_candidates.length}`}>
            {data.rung2_candidates.length === 0 ? (
              <p className="text-sm text-muted-foreground" role="status">
                No deterministic candidates yet.
              </p>
            ) : (
              <LaneBoard candidates={data.rung2_candidates} capabilityId={capabilityId} />
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function FunnelStrip({
  funnel,
  embedded = false,
}: {
  funnel: RunResultsDto["funnel"];
  /** Inside capability chrome — flat chips, no nested surface. */
  embedded?: boolean;
}) {
  const [more, setMore] = useState(false);
  const ready =
    funnel.n_rung1_candidates + funnel.n_rung2_candidates;
  const primary = [
    ["in-scope", funnel.n_in_scope_spans],
    ["gaps", funnel.n_uncovered],
    ["ready to decide", ready],
  ] as const;
  const extra = [
    ["spans", funnel.n_spans],
    ["clusters", funnel.n_clusters],
    ["unmatched", funnel.n_unmatched],
    ["promote to skill", funnel.n_rung1_candidates],
    ["make deterministic", funnel.n_rung2_candidates],
  ] as const;

  return (
    <div
      role="region"
      className={
        embedded
          ? "flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-border/70 pt-2 text-sm"
          : "section-surface flex flex-wrap items-baseline gap-x-4 gap-y-1 px-3 py-2 text-sm"
      }
      aria-label="funnel"
      data-testid="funnel-strip"
    >
      {primary.map(([label, n], i) => (
        <span key={label} className="inline-flex items-baseline gap-x-3 whitespace-nowrap">
          {embedded && i > 0 && (
            <span aria-hidden className="text-border">
              ·
            </span>
          )}
          <span>
            <strong className="tabular-nums text-foreground">{n}</strong>{" "}
            <span className="text-muted-foreground">{label}</span>
          </span>
        </span>
      ))}
      <button
        type="button"
        className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        aria-expanded={more}
        onClick={() => setMore((v) => !v)}
        data-testid="funnel-more"
      >
        {more ? "Less" : "More"}
      </button>
      {more &&
        extra.map(([label, n]) => (
          <span key={label} className="whitespace-nowrap text-xs">
            <strong className="tabular-nums text-foreground">{n}</strong>{" "}
            <span className="text-muted-foreground">{label}</span>
          </span>
        ))}
    </div>
  );
}

function VersionCompare({
  compare,
  isLoading,
  error,
  title,
}: {
  compare: RunCompareDto | undefined;
  isLoading: boolean;
  error: unknown;
  title: string;
}) {
  return (
    <Panel
      title={title}
      subtitle="Gaps closed, new gaps, skill hash changes, candidates advancing"
      isLoading={isLoading}
      error={error}
    >
      {compare && (
        <div className="space-y-2 text-sm">
          <p className="text-muted-foreground">
            {formatHumanDateTime(compare.from_run.run_id)} →{" "}
            {formatHumanDateTime(compare.to_run.run_id)} · {compare.from_run.n_gaps}{" "}
            gaps → {compare.to_run.n_gaps} gaps · closed {compare.gaps_closed.length} ·
            new {compare.gaps_new.length}
          </p>

          <HashChanges changes={compare.skill_hash_changes} />

          {compare.gaps_closed.length > 0 && (
            <GapList label="Gaps closed" rows={compare.gaps_closed} />
          )}
          {compare.gaps_new.length > 0 && (
            <GapList label="New gaps" rows={compare.gaps_new} />
          )}

          {compare.candidates_advancing.length > 0 ? (
            <div>
              <p className="mb-0.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Candidates advancing
              </p>
              <ul className="space-y-0.5">
                {compare.candidates_advancing.map((c) => (
                  <li key={c.candidate_id} className="text-sm">
                    <span className="font-medium">{c.title || c.candidate_id}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      · {c.rung === "skill" ? "promote to skill" : "make deterministic"} ·{" "}
                      {c.from_status ?? "new"} → {c.to_status}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-muted-foreground">No candidates advanced between versions.</p>
          )}
        </div>
      )}
    </Panel>
  );
}

function HashChanges({
  changes,
}: {
  changes: RunCompareDto["skill_hash_changes"];
}) {
  if (
    !changes.added.length &&
    !changes.removed.length &&
    !changes.changed.length
  ) {
    return (
      <p className="text-muted-foreground">
        Skill files unchanged
        {changes.unchanged.length
          ? ` (${changes.unchanged.length} file${changes.unchanged.length === 1 ? "" : "s"})`
          : ""}
        .
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {changes.changed.map((c) => (
        <Badge key={c.filename} variant="warn">
          {c.filename} updated
        </Badge>
      ))}
      {changes.added.map((f) => (
        <Badge key={f} variant="ready">
          {f} added
        </Badge>
      ))}
      {changes.removed.map((f) => (
        <Badge key={f} variant="outline">
          {f} removed
        </Badge>
      ))}
    </div>
  );
}

function GapList({
  label,
  rows,
}: {
  label: string;
  rows: RunCompareDto["gaps_closed"];
}) {
  return (
    <div>
      <p className="mb-0.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <ul className="space-y-0.5">
        {rows.slice(0, 8).map((g) => (
          <li key={g.cluster_id} className="truncate text-sm">
            {g.representative || g.cluster_id}
            <span className="text-muted-foreground">
              {" "}
              · {g.count} asks · {g.reason}
            </span>
          </li>
        ))}
        {rows.length > 8 && (
          <li className="text-sm text-muted-foreground">+{rows.length - 8} more</li>
        )}
      </ul>
    </div>
  );
}
