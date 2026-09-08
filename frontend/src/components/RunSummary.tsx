export interface RunLike {
  run_id?: string;
  window_start?: string;
  window_end?: string;
  n_spans?: number;
  n_in_scope_spans?: number;
  n_clusters?: number;
  n_rung1_candidates?: number;
  n_rung2_candidates?: number;
  status?: string;
  notes?: string[] | string;
}

export function RunSummary({ run }: { run: RunLike | null }) {
  if (!run || !run.run_id) {
    return <p className="text-sm text-muted-foreground">No runs yet.</p>;
  }
  const notes =
    typeof run.notes === "string"
      ? safeJsonArray(run.notes)
      : Array.isArray(run.notes)
        ? run.notes
        : [];
  return (
    <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
      <p className="font-medium">
        {run.run_id.slice(0, 16)} · {run.status}
      </p>
      <p className="text-muted-foreground">
        {run.n_spans ?? 0} spans, {run.n_in_scope_spans ?? 0} in scope →{" "}
        {run.n_clusters ?? 0} clusters · Rung 1: {run.n_rung1_candidates ?? 0} · Rung 2:{" "}
        {run.n_rung2_candidates ?? 0}
      </p>
      {notes.map((n) => (
        <p key={n} className="text-xs text-muted-foreground">
          · {n}
        </p>
      ))}
    </div>
  );
}

function safeJsonArray(s: string): string[] {
  try {
    const v: unknown = JSON.parse(s);
    return Array.isArray(v) ? (v as string[]) : [];
  } catch {
    return [];
  }
}
