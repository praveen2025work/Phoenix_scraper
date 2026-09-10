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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatHumanDate, formatHumanDateTime } from "@/lib/dates";

function shortHash(h: string): string {
  return h.slice(0, 8);
}

export function RunResults({
  capabilityId,
  runId,
  onRunNext,
  onBrowseHistory,
}: {
  capabilityId: string;
  runId: string;
  onRunNext: () => void;
  onBrowseHistory?: () => void;
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
  const latestRunId = runs.data?.[0]?.run_id ?? null;
  const isLatest = !latestRunId || latestRunId === runId;

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
    <div className="space-y-5" data-testid="run-results">
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-display text-xl font-semibold tracking-tight sm:text-2xl">
                Version · {formatHumanDateTime(data.run_id)}
              </h2>
              {isLatest ? (
                <Badge variant="ready" data-testid="latest-run-badge">
                  Latest
                </Badge>
              ) : (
                <Badge variant="outline" data-testid="older-run-badge">
                  Older version
                </Badge>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              Window {formatHumanDate(data.window_start)} →{" "}
              {formatHumanDate(data.window_end)} · {data.status}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button size="lg" onClick={onRunNext}>
              Run next version
            </Button>
            {onBrowseHistory && (
              <Button variant="outline" onClick={onBrowseHistory}>
                Browse history
              </Button>
            )}
            <Button variant="outline" asChild>
              <Link to={`/c/${capabilityId}/analytics`}>Usage</Link>
            </Button>
          </div>
        </div>

        <OutcomeBanner
          title="Next"
          dismissible
          dismissKey={`results-next-${capabilityId}`}
        >
          Review gaps, then use the promotion queue. Accept = decision; Write skill
          file = materialize. Same-day versions don&apos;t block each other.
        </OutcomeBanner>

        {!isLatest && (
          <p
            className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
            role="status"
            data-testid="older-run-note"
          >
            Viewing an older snapshot. Decisions still apply to the live candidate —
            promote anytime; History is for comparison.
          </p>
        )}

        <FunnelStrip funnel={funnel} />

        {Object.keys(data.skill_hashes).length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Skills frozen:{" "}
            {Object.entries(data.skill_hashes)
              .map(([f, h]) => `${f} (${shortHash(h)})`)
              .join(", ")}
          </p>
        ) : (
          <p
            className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm"
            role="status"
          >
            No skill MD files at run start. Upload on Setup, then Run now.
          </p>
        )}

        {data.warnings.length > 0 && (
          <div className="space-y-0.5" role="alert">
            {data.warnings.map((w) => (
              <p key={w} className="text-sm text-destructive">
                {w}
              </p>
            ))}
          </div>
        )}
      </header>

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
            Boards for this version&apos;s candidates. Accept first; write the file from
            the candidate page (see queue above).
          </p>
        </div>
        <Panel
          title={`Promote to skill · ${data.rung1_candidates.length}`}
          subtitle="Open a card to accept, then write the skill file"
        >
          {data.rung1_candidates.length === 0 ? (
            <p className="text-sm text-muted-foreground" role="status">
              No skill-promotion candidates yet.
            </p>
          ) : (
            <LaneBoard candidates={data.rung1_candidates} capabilityId={capabilityId} />
          )}
        </Panel>

        <Panel
          title={`Make deterministic · ${data.rung2_candidates.length}`}
          subtitle="Open a card to accept, then write the deterministic draft"
        >
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
  );
}

function FunnelStrip({ funnel }: { funnel: RunResultsDto["funnel"] }) {
  const cells = [
    ["spans", funnel.n_spans],
    ["in-scope", funnel.n_in_scope_spans],
    ["clusters", funnel.n_clusters],
    ["gaps", funnel.n_uncovered],
    ["unmatched", funnel.n_unmatched],
    ["promote to skill", funnel.n_rung1_candidates],
    ["make deterministic", funnel.n_rung2_candidates],
  ] as const;
  return (
    <div
      className="section-surface flex flex-wrap gap-x-4 gap-y-1.5 px-3 py-2.5 text-sm"
      aria-label="funnel"
    >
      {cells.map(([label, n]) => (
        <span key={label} className="whitespace-nowrap">
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
