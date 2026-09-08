import { type Row, useScoped } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { QualityByDimension } from "./QualityByDimension";
import { num, pct, truncate } from "./format";

export function QualitySection({ id }: { id: string }) {
  const checks = useScoped<Row[]>("checks", "/quality/checks", id);
  const byPrompt = useScoped<Row[]>("qbyprompt", "/quality/by-prompt", id);
  const failures = useScoped<Row[]>("fails", "/quality/failures?top=25", id);

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-muted-foreground">Answer quality</h3>

      <Panel
        title="Validation scoreboard"
        subtitle="every check, how often it applied and failed"
        isLoading={checks.isLoading}
        error={checks.error}
      >
        <DataTable
          rows={checks.data}
          columns={[
            { key: "check", header: "check" },
            { key: "target", header: "target" },
            { key: "n_evaluated", header: "applied", align: "right", format: (v) => num(v) },
            { key: "n_failed", header: "failed", align: "right", format: (v) => num(v) },
            { key: "fail_rate", header: "fail rate", align: "right", format: (v) => pct(v) },
            { key: "example", header: "example", format: (v) => truncate(v, 80) },
          ]}
        />
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <QualityByDimension id={id} dimension="user_id" title="Answer quality by user" />
        <QualityByDimension id={id} dimension="model_name" title="Answer quality by model" />
      </div>

      <Panel
        title="Prompt patterns answered badly"
        subtitle="frequency × failure — the strongest case for a new skill"
        isLoading={byPrompt.isLoading}
        error={byPrompt.error}
      >
        <DataTable
          rows={(byPrompt.data ?? []).slice().sort(
            (a, b) => Number(b.priority ?? 0) - Number(a.priority ?? 0),
          )}
          columns={[
            { key: "representative", header: "pattern", format: (v) => truncate(v, 60) },
            { key: "count", header: "asks", align: "right", format: (v) => num(v) },
            { key: "span_fail_rate", header: "fail rate", align: "right", format: (v) => pct(v) },
            { key: "top_issues", header: "top issues", format: (v) => String(v ?? "—") },
            { key: "priority", header: "priority", align: "right", format: (v) => num(v) },
          ]}
        />
      </Panel>

      <Panel
        title="Failed spans"
        subtitle="each failing span — confirm or dismiss the finding yourself"
        isLoading={failures.isLoading}
        error={failures.error}
      >
        <DataTable
          rows={failures.data}
          columns={[
            { key: "span_id", header: "span", format: (v) => String(v ?? "").slice(-14) },
            { key: "user_id", header: "user" },
            { key: "model_name", header: "model", format: (v) => String(v ?? "").split(".").pop() ?? "" },
            { key: "workflow_stage", header: "stage" },
            { key: "failed_checks", header: "failed checks" },
          ]}
        />
      </Panel>
    </section>
  );
}
