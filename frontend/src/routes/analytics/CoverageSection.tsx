import { useState } from "react";
import { type Row, useScoped } from "@/api/hooks";
import { DataTable } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Badge } from "@/components/ui/badge";
import { num, truncate } from "./format";

function YamlBlockCell({ row }: { row: Row }) {
  const [open, setOpen] = useState(false);
  const block = String(row.yaml_block ?? "");
  if (!block) return <span className="text-muted-foreground">—</span>;
  return (
    <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-xs text-muted-foreground">
        {open ? "hide" : "show"} block
      </summary>
      <pre className="mt-1 overflow-x-auto rounded border border-border p-2 text-xs">
        {block}
      </pre>
    </details>
  );
}

export function CoverageSection({ id }: { id: string }) {
  const coverage = useScoped("cov", "/skills/coverage", id);
  const updates = useScoped("updates", "/skills/updates", id);
  const gaps = useScoped("gaps", "/skills/gaps", id);
  const health = useScoped("health", "/insights/skill-health", id);

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-muted-foreground">Coverage &amp; skills</h3>

      <Panel
        title="Skill coverage"
        subtitle="per skill file: asks routed to it vs asks it demonstrates"
        isLoading={coverage.isLoading}
        error={coverage.error}
      >
        <DataTable
          rows={coverage.data}
          columns={[
            { key: "skill_name", header: "skill" },
            {
              key: "asks_routed",
              header: "asked",
              align: "right",
              format: (v, r) => num(v ?? r.count),
            },
            { key: "n_declared_examples", header: "demonstrated", align: "right", format: (v) => num(v) },
            { key: "covered", header: "covered", format: (v) => (v ? "✓" : "") },
          ]}
        />
      </Panel>

      <Panel
        title="What to add to each skill"
        subtitle="paste-ready example_prompts / keywords for the matched skill file"
        isLoading={updates.isLoading}
        error={updates.error}
      >
        <DataTable
          rows={updates.data}
          columns={[
            { key: "skill_name", header: "skill" },
            { key: "source_file", header: "file" },
            { key: "n_new_prompts", header: "new prompts", align: "right", format: (v) => num(v) },
            { key: "uncovered_asks", header: "uncovered asks", align: "right", format: (v) => num(v) },
            { key: "n_users", header: "users", align: "right", format: (v) => num(v) },
            { key: "yaml_block", header: "block", format: (_v, r) => <YamlBlockCell row={r} /> },
          ]}
        />
      </Panel>

      <Panel
        title="Proposed new skills"
        subtitle="frequent asks no existing skill covers"
        isLoading={gaps.isLoading}
        error={gaps.error}
      >
        <DataTable
          rows={gaps.data}
          columns={[
            { key: "proposed_name", header: "proposed" },
            { key: "level", header: "level" },
            { key: "capability", header: "capability", format: (v) => String(v ?? "—") },
            { key: "evidence_count", header: "asks", align: "right", format: (v) => num(v) },
            { key: "representative_prompt", header: "example", format: (v) => truncate(v, 70) },
          ]}
        />
      </Panel>

      <Panel
        title="Skill health"
        subtitle="matched skills whose clusters still take long routes are flagged"
        isLoading={health.isLoading}
        error={health.error}
      >
        <DataTable
          rows={health.data}
          columns={[
            { key: "skill_name", header: "skill" },
            { key: "n_asks", header: "asks", align: "right", format: (v) => num(v) },
            { key: "avg_route_len", header: "route", align: "right", format: (v) => num(v, 2) },
            {
              key: "error_rate",
              header: "errors",
              align: "right",
              format: (v) => `${Math.round(Number(v ?? 0) * 100)}%`,
            },
            {
              key: "status",
              header: "status",
              format: (v) => (
                <Badge variant={v === "effective" ? "ready" : "warn"}>{String(v)}</Badge>
              ),
            },
          ]}
        />
      </Panel>
    </section>
  );
}
